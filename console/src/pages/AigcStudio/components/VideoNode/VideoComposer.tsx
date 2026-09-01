import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  AudioLines,
  Camera,
  Clapperboard,
  FileText,
  Image,
  Layers,
  Languages,
  Maximize2,
  MousePointer2,
  Play,
  SlidersHorizontal,
  Sparkles,
  Wand2,
} from "lucide-react";

import styles from "../../index.module.less";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import { PromptFullscreenEditor } from "../PromptFullscreenEditor";
import {
  AIGC_REFERENCE_ASSET_MIME,
  insertReferenceAlias,
  readReferenceAssetDragData,
  writeReferenceAssetDragData,
} from "../referenceAssetDrag";
import { useAutoGrowTextarea } from "../useAutoGrowTextarea";
import {
  modelForNode,
  modelOptionsForCapability,
} from "../../nodeModelSelection";
import {
  VIDEO_CHARACTER_ASSETS,
  VIDEO_EFFECT_PRESETS,
  VIDEO_MOTION_PRESETS,
} from "./videoNodeState";
import type {
  VideoComposerProps,
  VideoConnectedInputs,
  VideoReferenceMode,
} from "./types";
import type { VideoCharacterAsset } from "./videoNodeState";

const VIDEO_TABS = [
  ["text_to_video", "文生视频"],
  ["all_reference", "全能参考"],
  ["image_to_video", "图生视频"],
  ["first_frame", "首尾帧"],
  ["image_reference", "图片参考"],
] as const;

type VideoTabKey = (typeof VIDEO_TABS)[number][0];
type VideoReferenceAsset = NonNullable<
  VideoComposerProps["referenceAssets"]
>[number];
type ReferenceMentionState = {
  query: string;
  start: number;
  end: number;
};

const VIDEO_CHARACTER_TABS = [
  ["real_person", "真人像"],
  ["image", "图片"],
  ["video", "视频"],
  ["audio", "音频"],
] as const satisfies readonly [VideoCharacterAsset["kind"], string][];

const MAX_VIDEO_CHARACTER_ASSETS = 9;
const DEFAULT_VIDEO_DURATION_MIN = 4;
const DEFAULT_VIDEO_DURATION_MAX = 15;
const DEFAULT_VIDEO_DURATION = 5;
const ASPECT_RATIO_PREVIEW_MAX_WIDTH = 18;
const ASPECT_RATIO_PREVIEW_MAX_HEIGHT = 12;
const ASPECT_RATIO_PREVIEW_MIN_EDGE = 4;
const VIDEO_ASPECT_RATIOS = [
  "Auto",
  "16:9",
  "4:3",
  "1:1",
  "3:4",
  "9:16",
  "21:9",
] as const;
const VIDEO_RESOLUTIONS = ["480P", "720P", "1080P"] as const;

const VIDEO_REFERENCE_MODES = new Set<string>([
  "all_reference",
  "image_to_video",
  "first_frame",
  "image_reference",
]);

const isVideoReferenceMode = (value: string): value is VideoReferenceMode =>
  VIDEO_REFERENCE_MODES.has(value);

const referenceModeVideoMode = (mode: VideoReferenceMode) =>
  mode === "first_frame" ? "first_last_frames" : mode;

const EMPTY_CONNECTED_INPUTS: VideoConnectedInputs = {
  imageCount: 0,
  videoCount: 0,
  audioCount: 0,
  totalCount: 0,
};

const recordFrom = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const numberFrom = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const firstPositiveNumber = (values: unknown[]): number | null => {
  for (const value of values) {
    const parsed = numberFrom(value);
    if (parsed !== null && parsed > 0) return parsed;
  }
  return null;
};

const clampVideoDuration = (
  value: unknown,
  constraints: { min: number; max: number; defaultValue: number },
) => {
  const parsed = numberFrom(value) ?? constraints.defaultValue;
  return Math.min(
    constraints.max,
    Math.max(constraints.min, Math.round(parsed)),
  );
};

function videoDurationConstraintsFor(
  model: VideoComposerProps["currentModel"],
) {
  const schema = recordFrom(model?.parameter_schema);
  const properties = recordFrom(schema.properties);
  const duration = recordFrom(properties.duration);
  const min = Math.round(
    firstPositiveNumber([
      schema.min_duration,
      schema.minDuration,
      duration.minimum,
      duration.min,
    ]) ?? DEFAULT_VIDEO_DURATION_MIN,
  );
  const rawMax = Math.round(
    firstPositiveNumber([
      schema.max_duration,
      schema.maxDuration,
      schema.durationMax,
      duration.maximum,
      duration.max,
    ]) ?? DEFAULT_VIDEO_DURATION_MAX,
  );
  const max = Math.max(min, rawMax);
  const defaultValue = clampVideoDuration(
    firstPositiveNumber([duration.default, schema.default_duration]) ??
      DEFAULT_VIDEO_DURATION,
    { min, max, defaultValue: DEFAULT_VIDEO_DURATION },
  );
  return { min, max, defaultValue };
}

function schemaStringOptionsFor(
  model: VideoComposerProps["currentModel"],
  propertyNames: string[],
  fallback: readonly string[],
) {
  const schema = recordFrom(model?.parameter_schema);
  const properties = recordFrom(schema.properties);
  for (const propertyName of propertyNames) {
    const property = recordFrom(properties[propertyName]);
    const options = Array.isArray(property.enum)
      ? property.enum.filter(
          (item): item is string =>
            typeof item === "string" && Boolean(item.trim()),
        )
      : [];
    if (options.length > 0) return options;
  }
  return [...fallback];
}

const videoAspectRatioOptionsFor = (
  model: VideoComposerProps["currentModel"],
) =>
  schemaStringOptionsFor(
    model,
    ["aspect_ratio", "aspectRatio", "ratio"],
    VIDEO_ASPECT_RATIOS,
  );

const videoResolutionOptionsFor = (model: VideoComposerProps["currentModel"]) =>
  schemaStringOptionsFor(
    model,
    ["resolution", "resolution_name", "videoResolution"],
    VIDEO_RESOLUTIONS,
  );

const videoSupportsAudioFor = (model: VideoComposerProps["currentModel"]) => {
  const properties = recordFrom(recordFrom(model?.parameter_schema).properties);
  return ["generate_audio", "videoAudio"].some((propertyName) =>
    Object.prototype.hasOwnProperty.call(properties, propertyName),
  );
};

const preferredVideoModeFor = (model: VideoComposerProps["currentModel"]) =>
  String(recordFrom(model?.parameter_schema).preferred_video_mode ?? "");

const aspectRatioPreviewStyle = (ratio: string): CSSProperties => {
  const [width, height] = ratio.split(":").map((part) => Number(part));
  if (!Number.isFinite(width) || !Number.isFinite(height)) {
    return { width: 10, height: 10 };
  }
  if (width <= 0 || height <= 0) {
    return { width: 10, height: 10 };
  }

  const scale = Math.min(
    ASPECT_RATIO_PREVIEW_MAX_WIDTH / width,
    ASPECT_RATIO_PREVIEW_MAX_HEIGHT / height,
  );
  return {
    width: Math.max(ASPECT_RATIO_PREVIEW_MIN_EDGE, Math.round(width * scale)),
    height: Math.max(ASPECT_RATIO_PREVIEW_MIN_EDGE, Math.round(height * scale)),
  };
};

const isTextReferenceAsset = (asset: VideoReferenceAsset) => {
  const kind = String(asset.kind ?? "")
    .trim()
    .toLowerCase();
  const previewUrl = String(asset.previewUrl ?? "")
    .trim()
    .toLowerCase();
  const sourceId = String(asset.sourceNodeId ?? asset.id ?? "")
    .trim()
    .toLowerCase();
  return (
    kind === "text" ||
    kind === "prompt" ||
    previewUrl === "prompt" ||
    sourceId.startsWith("prompt-")
  );
};

const hasImageReferencePreview = (asset: VideoReferenceAsset) => {
  const previewUrl = String(asset.previewUrl ?? "").trim();
  if (!previewUrl || isTextReferenceAsset(asset)) return false;
  return (
    /^(blob:|data:image\/|https?:\/\/|\/|\.\/|\.\.\/)/i.test(previewUrl) ||
    /[/.]/.test(previewUrl)
  );
};

const referenceAssetPreview = (asset: VideoReferenceAsset, size = 18) => {
  if (hasImageReferencePreview(asset)) {
    return <AuthenticatedAssetImage src={asset.previewUrl} alt={asset.name} />;
  }
  if (isTextReferenceAsset(asset)) {
    return <FileText size={size} data-testid="aigc-text-reference-icon" />;
  }
  return <Image size={size} />;
};

const referenceAssetBadgeNumber = (
  alias: VideoReferenceAsset["alias"],
  fallback: number,
) => {
  const match = String(alias ?? "").match(/\d+/);
  return match?.[0] ?? String(fallback);
};

const referenceMentionStateFromText = (
  text: string,
  cursorPosition: number,
): ReferenceMentionState | null => {
  const beforeCursor = text.slice(0, cursorPosition);
  const match = beforeCursor.match(/(^|\s)@([^\s@]*)$/);
  if (!match) return null;
  const query = match[2] ?? "";
  return {
    query,
    start: cursorPosition - query.length - 1,
    end: cursorPosition,
  };
};

const existingReferencedAssets = (value: unknown) =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object",
      )
    : [];

function videoModeStateForInputs(
  key: VideoTabKey,
  inputs: VideoConnectedInputs,
) {
  const mediaCount = inputs.totalCount;
  const visualCount = inputs.imageCount + inputs.videoCount;
  const imageOnly =
    inputs.imageCount > 0 && inputs.videoCount === 0 && inputs.audioCount === 0;

  if (key === "text_to_video") {
    return mediaCount === 0
      ? { enabled: true, reason: "" }
      : {
          enabled: false,
          reason: "已连接媒体输入，无法使用纯文生视频",
        };
  }
  if (key === "all_reference") {
    if (mediaCount === 0) {
      return {
        enabled: false,
        reason: "需要连接图片/视频节点（1~15个）",
      };
    }
    if (mediaCount > 15) {
      return {
        enabled: false,
        reason: "最多连接15个参考素材",
      };
    }
    if (visualCount === 0) {
      return {
        enabled: false,
        reason: "音频不能单独作为全能参考，需要连接图片或视频节点",
      };
    }
    return { enabled: true, reason: "" };
  }
  if (key === "image_to_video") {
    return inputs.imageCount === 1 && imageOnly
      ? { enabled: true, reason: "" }
      : {
          enabled: false,
          reason: "需要连接图片节点（1个）",
        };
  }
  if (key === "first_frame") {
    return inputs.imageCount === 2 && imageOnly
      ? { enabled: true, reason: "" }
      : {
          enabled: false,
          reason: "需要连接图片节点（2个）",
        };
  }
  if (key === "image_reference") {
    return imageOnly && inputs.imageCount <= 15
      ? { enabled: true, reason: "" }
      : {
          enabled: false,
          reason: "需要连接图片节点（1~15个）",
        };
  }
  return { enabled: false, reason: "" };
}

function recommendedVideoTabForInputs(inputs: VideoConnectedInputs) {
  if (inputs.totalCount === 0) return "text_to_video";
  if (
    inputs.imageCount === 1 &&
    inputs.videoCount === 0 &&
    inputs.audioCount === 0
  ) {
    return "image_to_video";
  }
  if (videoModeStateForInputs("all_reference", inputs).enabled) {
    return "all_reference";
  }
  if (videoModeStateForInputs("first_frame", inputs).enabled) {
    return "first_frame";
  }
  if (videoModeStateForInputs("image_reference", inputs).enabled) {
    return "image_reference";
  }
  return "text_to_video";
}

export function VideoComposer({
  node,
  videoComposerMenu,
  currentModel,
  modelOptions,
  currentModelKey,
  connectedInputs = EMPTY_CONNECTED_INPUTS,
  referenceAssets = [],
  t,
  workflow,
  disabled = false,
  onUpdateNodeData,
  onToggleMenu,
  onSelectModel,
  onCloseMenu,
}: VideoComposerProps) {
  const [activeTooltip, setActiveTooltip] = useState<
    "promptOptimize" | "translatePrompt" | null
  >(null);
  const [composerFullscreenOpen, setComposerFullscreenOpen] = useState(false);
  const [activeCharacterTab, setActiveCharacterTab] = useState<
    VideoCharacterAsset["kind"] | "all"
  >("all");
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const draggedReferenceAssetRef = useRef<VideoReferenceAsset | null>(null);
  const [referenceMention, setReferenceMention] =
    useState<ReferenceMentionState | null>(null);
  const composerTextValue = String(
    node.data.composerText ?? node.data.text ?? "",
  );
  const [composerDraftText, setComposerDraftText] = useState(composerTextValue);
  useAutoGrowTextarea(composerDraftText, composerInputRef);
  const composerNodeIdRef = useRef(node.id);
  const composerTextValueRef = useRef(composerTextValue);
  const characterAssetIds = Array.isArray(node.data.characterAssetIds)
    ? (node.data.characterAssetIds as string[])
    : [];
  const characterAssetNames = Array.isArray(node.data.characterAssetNames)
    ? (node.data.characterAssetNames as string[])
    : [];
  const rawActiveVideoTab = String(node.data.activeVideoTab ?? "text_to_video");
  const activeVideoTab = VIDEO_TABS.some(([key]) => key === rawActiveVideoTab)
    ? (rawActiveVideoTab as VideoTabKey)
    : "text_to_video";
  const videoModeStates = Object.fromEntries(
    VIDEO_TABS.map(([key]) => [
      key,
      videoModeStateForInputs(key, connectedInputs),
    ]),
  ) as Record<VideoTabKey, { enabled: boolean; reason: string }>;
  const visibleActiveVideoTab = videoModeStates[activeVideoTab].enabled
    ? activeVideoTab
    : recommendedVideoTabForInputs(connectedInputs);
  const effectiveVideoMode = isVideoReferenceMode(visibleActiveVideoTab)
    ? referenceModeVideoMode(visibleActiveVideoTab)
    : "text_to_video";
  const visibleCharacterAssets =
    activeCharacterTab === "all"
      ? VIDEO_CHARACTER_ASSETS
      : VIDEO_CHARACTER_ASSETS.filter(
          (asset) => asset.kind === activeCharacterTab,
        );
  const videoModelOptions = modelOptionsForCapability(
    modelOptions,
    "text_to_video",
  );
  const currentVideoGenerationModel =
    currentModel &&
    modelOptionsForCapability([currentModel], "text_to_video").length
      ? currentModel
      : null;
  const selectedVideoModel =
    currentVideoGenerationModel ??
    modelForNode(modelOptions, node, "text_to_video");
  const videoDurationConstraints =
    videoDurationConstraintsFor(selectedVideoModel);
  const videoAspectRatioOptions =
    videoAspectRatioOptionsFor(selectedVideoModel);
  const videoResolutionOptions = videoResolutionOptionsFor(selectedVideoModel);
  const supportsVideoAudio = videoSupportsAudioFor(selectedVideoModel);
  const selectedVideoDuration = clampVideoDuration(
    node.data.videoDuration,
    videoDurationConstraints,
  );
  const modelLabel = String(
    selectedVideoModel?.model_name ??
      selectedVideoModel?.model_id ??
      t("aigcStudio.videoNode.noModel", "未选择视频模型"),
  );
  const tooltipText =
    activeTooltip === "promptOptimize"
      ? t("aigcStudio.videoNode.promptOptimize", "提示词优化")
      : activeTooltip === "translatePrompt"
      ? t("aigcStudio.videoNode.translatePrompt", "翻译提示词")
      : "";
  const videoComposerPlaceholder = String(
    node.data.composerPlaceholder ??
      t(
        "aigcStudio.videoNode.composer.placeholder",
        "描述你想要生成的画面内容，@引用素材",
      ),
  );
  const visibleReferenceAssets = useMemo<VideoReferenceAsset[]>(() => {
    if (referenceAssets.length > 0) return referenceAssets;
    const previewUrl = String(node.data.referencePreviewUrl ?? "").trim();
    if (node.data.referenceThumb === true && previewUrl) {
      return [
        {
          id: String(node.data.referenceAssetId ?? previewUrl),
          alias: "图片1",
          name: String(node.data.referenceAssetName ?? "参考素材"),
          previewUrl,
          sourceNodeId:
            typeof node.data.referenceSourceNodeId === "string"
              ? node.data.referenceSourceNodeId
              : undefined,
        },
      ];
    }
    return [];
  }, [
    node.data.referenceAssetId,
    node.data.referenceAssetName,
    node.data.referencePreviewUrl,
    node.data.referenceSourceNodeId,
    node.data.referenceThumb,
    referenceAssets,
  ]);
  const referenceMentionOptions = useMemo(() => {
    const query = (referenceMention?.query ?? "").toLowerCase();
    return visibleReferenceAssets.filter((asset) => {
      if (!query) return true;
      return [asset.alias, asset.name, asset.id]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [referenceMention, visibleReferenceAssets]);
  useEffect(() => {
    if (composerNodeIdRef.current !== node.id) {
      composerNodeIdRef.current = node.id;
      composerTextValueRef.current = composerTextValue;
      setComposerDraftText(composerTextValue);
      return;
    }
    if (composerTextValue !== composerTextValueRef.current) {
      composerTextValueRef.current = composerTextValue;
      setComposerDraftText(composerTextValue);
    }
  }, [composerTextValue, node.id]);
  const applyReferenceMentionText = (
    value: string,
    cursorPosition = value.length,
  ) => {
    setReferenceMention(referenceMentionStateFromText(value, cursorPosition));
  };
  const updateComposerText = (value: string, cursorPosition = value.length) => {
    setComposerDraftText(value);
    applyReferenceMentionText(value, cursorPosition);
    onUpdateNodeData(node.id, {
      composerText: value,
      text: value,
    });
  };
  const currentComposerText = () => {
    const refValue = composerInputRef.current?.value;
    const nodeValue = String(node.data.composerText ?? node.data.text ?? "");
    if (typeof refValue === "string" && refValue.trim()) return refValue;
    if (composerDraftText.trim()) return composerDraftText;
    if (nodeValue.trim()) return nodeValue;
    if (typeof refValue === "string") return refValue;
    return nodeValue;
  };
  const selectReferenceMention = (asset: VideoReferenceAsset) => {
    const text = currentComposerText();
    const mention =
      referenceMention ?? referenceMentionStateFromText(text, text.length);
    if (!mention) return;
    const nextText = `${text.slice(0, mention.start)}@${
      asset.alias
    } ${text.slice(mention.end)}`;
    const existing = existingReferencedAssets(node.data.referencedAssets);
    const nextReferencedAssets = [
      ...existing.filter(
        (item) =>
          String(item.previewUrl ?? item.url ?? item.assetPreviewUrl ?? "") !==
          asset.previewUrl,
      ),
      asset,
    ];
    setReferenceMention(null);
    setComposerDraftText(nextText);
    onUpdateNodeData(node.id, {
      composerText: nextText,
      text: nextText,
      referencedAssets: nextReferencedAssets,
      inputUpdated: true,
    });
  };
  const commitDraggedReferenceAsset = (
    asset: VideoReferenceAsset,
    nextText: string,
    cursor?: number,
  ) => {
    const existing = existingReferencedAssets(node.data.referencedAssets);
    const nextReferencedAssets = [
      ...existing.filter(
        (item) =>
          String(item.previewUrl ?? item.url ?? item.assetPreviewUrl ?? "") !==
          asset.previewUrl,
      ),
      asset,
    ];
    setReferenceMention(null);
    setComposerDraftText(nextText);
    onUpdateNodeData(node.id, {
      composerText: nextText,
      text: nextText,
      referencedAssets: nextReferencedAssets,
      inputUpdated: true,
    });
    if (cursor !== undefined) {
      window.requestAnimationFrame(() => {
        composerInputRef.current?.focus();
        composerInputRef.current?.setSelectionRange(cursor, cursor);
      });
    }
  };
  const insertDraggedReferenceAsset = (
    asset: VideoReferenceAsset,
    text: string,
    selectionStart: number,
    selectionEnd: number,
  ) => {
    const insertion = insertReferenceAlias(
      text,
      asset.alias,
      selectionStart,
      selectionEnd,
    );
    commitDraggedReferenceAsset(asset, insertion.value, insertion.cursor);
  };
  const toggleCharacterAsset = (assetId: string, assetName: string) => {
    const selected = characterAssetIds.includes(assetId);
    if (!selected && characterAssetIds.length >= MAX_VIDEO_CHARACTER_ASSETS) {
      return;
    }
    onUpdateNodeData(node.id, {
      characterAssetIds: selected
        ? characterAssetIds.filter((item) => item !== assetId)
        : [...characterAssetIds, assetId],
      characterAssetNames: selected
        ? characterAssetNames.filter((name) => name !== assetName)
        : [...characterAssetNames, assetName],
    });
  };

  return (
    <div
      className={styles.videoComposer}
      data-testid="aigc-video-composer"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className={styles.composerExpand}
        aria-label={t("aigcStudio.composer.fullscreen.open", "全屏编辑输入")}
        onClick={(event) => {
          event.stopPropagation();
          setComposerFullscreenOpen(true);
        }}
      >
        <Maximize2 size={15} />
      </button>
      <div className={styles.videoTabs}>
        {VIDEO_TABS.map(([key, label]) => {
          const state = videoModeStates[key];
          return (
            <button
              type="button"
              key={key}
              className={
                visibleActiveVideoTab === key ? styles.videoTabActive : ""
              }
              disabled={!state.enabled}
              title={state.reason || undefined}
              onClick={() => {
                if (!state.enabled) return;
                onUpdateNodeData(node.id, {
                  activeVideoTab: key,
                  videoMode: isVideoReferenceMode(key)
                    ? referenceModeVideoMode(key)
                    : "text_to_video",
                  showTryOptions: false,
                });
              }}
            >
              {t(`aigcStudio.videoNode.tabs.${key}`, label)}
            </button>
          );
        })}
      </div>
      <div className={styles.composerTools}>
        <button
          type="button"
          className={
            node.data.activeTool === "mark" ? styles.imageToolActive : ""
          }
          onClick={() =>
            onUpdateNodeData(node.id, {
              activeTool: node.data.activeTool === "mark" ? null : "mark",
            })
          }
        >
          <MousePointer2 size={15} />
          {t("aigcStudio.mark", "标记")}
        </button>
        <button
          type="button"
          className={
            videoComposerMenu?.nodeId === node.id &&
            videoComposerMenu.menu === "effect"
              ? styles.imageToolActive
              : ""
          }
          onClick={() => onToggleMenu(node.id, "effect")}
        >
          <Sparkles size={15} />
          {t("aigcStudio.videoNode.effect", "特效")}
        </button>
        <button
          type="button"
          className={
            videoComposerMenu?.nodeId === node.id &&
            videoComposerMenu.menu === "character"
              ? styles.imageToolActive
              : ""
          }
          onClick={() => onToggleMenu(node.id, "character")}
        >
          <Layers size={15} />
          {t("aigcStudio.videoNode.characterLibrary", "角色库")}
        </button>
        {visibleReferenceAssets.length > 0
          ? visibleReferenceAssets.map((asset, index) => (
              <span
                className={styles.imageReferenceThumb}
                data-testid="aigc-video-reference-thumb"
                data-reference-alias={asset.alias}
                title={asset.name}
                key={`${asset.id}-${asset.previewUrl}`}
                draggable
                onDragStart={(event) => {
                  event.stopPropagation();
                  draggedReferenceAssetRef.current = asset;
                  writeReferenceAssetDragData(event.dataTransfer, asset);
                }}
                onDragEnd={(event) => {
                  event.stopPropagation();
                  draggedReferenceAssetRef.current = null;
                }}
              >
                {referenceAssetPreview(asset)}
                <em>{referenceAssetBadgeNumber(asset.alias, index + 1)}</em>
              </span>
            ))
          : node.data.referenceThumb === true && (
              <span
                className={styles.imageReferenceThumb}
                data-testid="aigc-video-reference-thumb"
              >
                <Image size={18} />
                <em>{Number(node.data.referenceCount ?? 1)}</em>
              </span>
            )}
        {characterAssetIds.length > 0 && (
          <span
            className={`${styles.imageReferenceThumb} ${styles.videoCharacterSummary}`}
            data-testid="aigc-video-character-summary"
            title={characterAssetNames.join("、")}
          >
            <Image size={18} />
            <em>{characterAssetIds.length}</em>
            {characterAssetNames.length > 0 && (
              <small>
                {characterAssetNames.slice(0, 2).join("、")}
                {characterAssetNames.length > 2 ? "..." : ""}
              </small>
            )}
          </span>
        )}
      </div>
      <textarea
        data-platform-control-id="aigc.video.prompt-input"
        ref={composerInputRef}
        className={`${styles.promptPlaceholder} ${styles.textComposerInput}`}
        value={composerDraftText}
        placeholder={videoComposerPlaceholder}
        aria-label={t("aigcStudio.videoNode.composerLabel", "视频节点输入")}
        onMouseDown={onCloseMenu}
        onFocus={onCloseMenu}
        onDragOver={(event) => {
          const carriesReference =
            draggedReferenceAssetRef.current !== null ||
            Array.from(event.dataTransfer.types).includes(
              AIGC_REFERENCE_ASSET_MIME,
            );
          if (!carriesReference) return;
          event.preventDefault();
          event.stopPropagation();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={(event) => {
          const asset =
            readReferenceAssetDragData(event.dataTransfer) ??
            draggedReferenceAssetRef.current;
          if (!asset) return;
          event.stopPropagation();
          draggedReferenceAssetRef.current = null;
          const textBeforeDrop = event.currentTarget.value;
          const fallbackStart =
            event.currentTarget.selectionStart ?? textBeforeDrop.length;
          const fallbackEnd = event.currentTarget.selectionEnd ?? fallbackStart;
          window.requestAnimationFrame(() => {
            const nativeDropText = composerInputRef.current?.value;
            if (
              typeof nativeDropText === "string" &&
              nativeDropText !== textBeforeDrop
            ) {
              commitDraggedReferenceAsset(asset, nativeDropText);
              return;
            }
            insertDraggedReferenceAsset(
              asset,
              textBeforeDrop,
              fallbackStart,
              fallbackEnd,
            );
          });
        }}
        onChange={(event) =>
          updateComposerText(
            event.target.value,
            event.target.selectionStart ?? event.target.value.length,
          )
        }
        onKeyUp={(event) =>
          applyReferenceMentionText(
            event.currentTarget.value,
            event.currentTarget.selectionStart ??
              event.currentTarget.value.length,
          )
        }
      />
      {referenceMention && referenceMentionOptions.length > 0 && (
        <div
          className={styles.referenceMentionMenu}
          data-testid="aigc-reference-mention-menu"
        >
          {referenceMentionOptions.map((asset) => (
            <button
              type="button"
              key={`${asset.id}-${asset.alias}`}
              aria-label={`${asset.alias} ${asset.name}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectReferenceMention(asset)}
            >
              <span className={styles.referenceMentionThumb}>
                {referenceAssetPreview(asset, 16)}
              </span>
              <span>
                <strong>{asset.alias}</strong>
                <small>{asset.name}</small>
              </span>
            </button>
          ))}
        </div>
      )}
      <div className={styles.parameterBar}>
        <button
          type="button"
          className={styles.textModelButton}
          data-platform-control-id="aigc.video.model-select"
          onClick={() => onToggleMenu(node.id, "model")}
        >
          {modelLabel}
          <span>⌃</span>
        </button>
        <button
          type="button"
          className={styles.imageParamButton}
          onClick={() => onToggleMenu(node.id, "settings")}
        >
          {String(node.data.aspectRatio ?? "16:9")} ·{" "}
          {String(node.data.videoResolution ?? "720P")} ·{" "}
          {selectedVideoDuration}s · <AudioLines size={14} />
          <span>⌃</span>
        </button>
        <button
          type="button"
          className={`${styles.imageParamButton} ${
            videoComposerMenu?.nodeId === node.id &&
            videoComposerMenu.menu === "motion"
              ? styles.imageParamActive
              : ""
          }`}
          onClick={() => onToggleMenu(node.id, "motion")}
        >
          <Camera size={14} />
          {t("aigcStudio.videoNode.motion", "运镜")}
        </button>
        <button
          type="button"
          className={styles.iconParamButton}
          aria-label={t("aigcStudio.videoNode.promptOptimize", "提示词优化")}
          onMouseEnter={() => setActiveTooltip("promptOptimize")}
          onMouseLeave={() => setActiveTooltip(null)}
          onFocus={() => setActiveTooltip("promptOptimize")}
          onBlur={() => setActiveTooltip(null)}
        >
          <Wand2 size={15} />
        </button>
        <button
          type="button"
          className={styles.iconParamButton}
          aria-label={t("aigcStudio.videoNode.translatePrompt", "翻译提示词")}
          onMouseEnter={() => setActiveTooltip("translatePrompt")}
          onMouseLeave={() => setActiveTooltip(null)}
          onFocus={() => setActiveTooltip("translatePrompt")}
          onBlur={() => setActiveTooltip(null)}
        >
          <Languages size={15} />
        </button>
        <button
          type="button"
          className={styles.iconParamButton}
          aria-label={t("aigcStudio.videoNode.advanced", "高级设置")}
          onClick={() => onToggleMenu(node.id, "advanced")}
        >
          <SlidersHorizontal size={15} />
        </button>
        <button
          type="button"
          className={styles.imageParamButton}
          onClick={() => onToggleMenu(node.id, "count")}
        >
          {t("aigcStudio.videoNode.countValue", "{{count}}个", {
            count: Number(node.data.videoCount ?? 1),
          })}
          <span>⌃</span>
        </button>
        <span>✦ 122/135</span>
        <button
          type="button"
          className={styles.runCircle}
          data-platform-control-id="aigc.video.generate-submit"
          aria-label={t(
            "aigcStudio.videoNode.submitComposer",
            "提交视频节点输入",
          )}
          onClick={(event) => {
            event.stopPropagation();
            workflow.handleVideoComposerSubmit({
              ...node,
              data: {
                ...node.data,
                composerText: composerDraftText,
                text: composerDraftText,
                activeVideoTab: visibleActiveVideoTab,
                videoMode: effectiveVideoMode,
              },
            });
          }}
          disabled={disabled}
        >
          <Play size={15} />
        </button>
      </div>
      {activeTooltip && (
        <div className={styles.paramTooltip} role="tooltip">
          {tooltipText}
        </div>
      )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "model" && (
          <div
            className={styles.videoModelMenu}
            data-testid="aigc-video-model-menu"
          >
            {videoModelOptions.length ? (
              videoModelOptions.map((model, index) => {
                const durationConstraints = videoDurationConstraintsFor(model);
                return (
                  <button
                    type="button"
                    key={`${model.provider_id}:${model.model_id}`}
                    className={
                      currentModelKey ===
                      `${model.provider_id}:${model.model_id}`
                        ? styles.textModelActive
                        : ""
                    }
                    onClick={() => {
                      const nextDurationConstraints =
                        videoDurationConstraintsFor(model);
                      const nextAspectRatios =
                        videoAspectRatioOptionsFor(model);
                      const nextResolutions = videoResolutionOptionsFor(model);
                      const currentAspectRatio = String(
                        node.data.aspectRatio ?? "16:9",
                      );
                      const currentResolution = String(
                        node.data.videoResolution ?? "720P",
                      );
                      const preferredVideoMode = preferredVideoModeFor(model);
                      onSelectModel(model);
                      onUpdateNodeData(node.id, {
                        videoDuration: clampVideoDuration(
                          node.data.videoDuration,
                          nextDurationConstraints,
                        ),
                        aspectRatio: nextAspectRatios.includes(
                          currentAspectRatio,
                        )
                          ? currentAspectRatio
                          : nextAspectRatios.includes("16:9")
                          ? "16:9"
                          : nextAspectRatios[0],
                        videoResolution: nextResolutions.includes(
                          currentResolution,
                        )
                          ? currentResolution
                          : nextResolutions.includes("720P")
                          ? "720P"
                          : nextResolutions[0],
                        ...(preferredVideoMode === "first_last_frames"
                          ? {
                              activeVideoTab: "first_frame",
                              videoMode: "first_last_frames",
                            }
                          : {}),
                      });
                    }}
                  >
                    <span className={styles.imageModelIcon}>
                      {index % 2 === 0 ? <Sparkles size={16} /> : "▧"}
                    </span>
                    <span>
                      <strong>{model.model_name ?? model.model_id}</strong>
                      {index === 0 && (
                        <small>
                          {t(
                            "aigcStudio.videoNode.modelHint",
                            "视频生成模型，按当前视频能力筛选",
                          )}
                        </small>
                      )}
                    </span>
                    <em>
                      {t(
                        "aigcStudio.videoNode.modelMaxDuration",
                        "最长{{seconds}}s",
                        {
                          seconds: durationConstraints.max,
                        },
                      )}
                    </em>
                  </button>
                );
              })
            ) : (
              <div className={styles.modelMenuEmpty}>
                <strong>
                  {t(
                    "aigcStudio.videoNode.noGenerationModels",
                    "暂无可用视频生成模型",
                  )}
                </strong>
                <small>
                  {t(
                    "aigcStudio.videoNode.configureGenerationModels",
                    "请在模型管理中为模型标注 text_to_video 或 image_to_video。",
                  )}
                </small>
              </div>
            )}
          </div>
        )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "settings" && (
          <div
            className={styles.videoSettingsMenu}
            data-testid="aigc-video-settings-menu"
          >
            <div className={styles.imageMenuTitle}>
              {t("aigcStudio.imageNode.aspectRatio", "比例")}
            </div>
            <div
              className={styles.videoRatioGrid}
              data-platform-control-id="aigc.video.aspect-ratio-select"
            >
              {videoAspectRatioOptions.map((ratio) => (
                <button
                  type="button"
                  key={ratio}
                  className={
                    node.data.aspectRatio === ratio
                      ? styles.imageOptionActive
                      : ""
                  }
                  onClick={() => {
                    onUpdateNodeData(node.id, {
                      aspectRatio: ratio,
                    });
                  }}
                >
                  <span
                    aria-hidden="true"
                    data-testid={`aigc-video-ratio-preview-${ratio}`}
                    style={aspectRatioPreviewStyle(ratio)}
                  />
                  {ratio}
                </button>
              ))}
            </div>
            <div className={styles.imageMenuTitle}>
              {t("aigcStudio.videoNode.resolution", "清晰度")}
            </div>
            <div className={styles.segmentGrid}>
              {videoResolutionOptions.map((resolution) => (
                <button
                  type="button"
                  key={resolution}
                  className={
                    node.data.videoResolution === resolution
                      ? styles.imageOptionActive
                      : ""
                  }
                  onClick={() => {
                    onUpdateNodeData(node.id, {
                      videoResolution: resolution,
                    });
                  }}
                >
                  {resolution}
                </button>
              ))}
            </div>
            <label
              className={styles.videoDuration}
              data-platform-control-id="aigc.video.duration-select"
            >
              {t("aigcStudio.videoNode.duration", "视频时长")}
              <input
                type="range"
                aria-label={t("aigcStudio.videoNode.duration", "视频时长")}
                min={videoDurationConstraints.min}
                max={videoDurationConstraints.max}
                value={selectedVideoDuration}
                onChange={(event) =>
                  onUpdateNodeData(node.id, {
                    videoDuration: clampVideoDuration(
                      event.target.value,
                      videoDurationConstraints,
                    ),
                  })
                }
              />
              <span>{selectedVideoDuration}s</span>
            </label>
            {supportsVideoAudio && (
              <>
                <div className={styles.imageMenuTitle}>
                  {t("aigcStudio.videoNode.generateAudio", "生成音频")}
                </div>
                <div className={styles.segmentGrid}>
                  <button
                    type="button"
                    className={
                      node.data.videoAudio !== false
                        ? styles.imageOptionActive
                        : ""
                    }
                    onClick={() => {
                      onUpdateNodeData(node.id, { videoAudio: true });
                    }}
                  >
                    {t("aigcStudio.videoNode.on", "开启")}
                  </button>
                  <button
                    type="button"
                    className={
                      node.data.videoAudio === false
                        ? styles.imageOptionActive
                        : ""
                    }
                    onClick={() => {
                      onUpdateNodeData(node.id, { videoAudio: false });
                    }}
                  >
                    {t("aigcStudio.videoNode.off", "关闭")}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "count" && (
          <div className={styles.countMenu} data-testid="aigc-video-count-menu">
            {[1, 2, 4].map((count) => (
              <button
                type="button"
                key={count}
                className={
                  Number(node.data.videoCount ?? 1) === count
                    ? styles.textModelActive
                    : ""
                }
                onClick={() => {
                  onUpdateNodeData(node.id, { videoCount: count });
                }}
              >
                {t("aigcStudio.videoNode.countValue", "{{count}}个", {
                  count,
                })}
              </button>
            ))}
          </div>
        )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "advanced" && (
          <div
            className={styles.advancedPanel}
            data-testid="aigc-video-advanced-menu"
          >
            <small>{t("aigcStudio.videoNode.advanced", "高级设置")}</small>
            <label>
              {t("aigcStudio.imageNode.webSearch", "联网搜索")}
              <input
                type="checkbox"
                checked={node.data.webSearch === true}
                onChange={(event) => {
                  onUpdateNodeData(node.id, {
                    webSearch: event.target.checked,
                  });
                }}
              />
            </label>
          </div>
        )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "effect" && (
          <div
            className={styles.effectLibrary}
            data-testid="aigc-video-effect-library"
          >
            <button
              type="button"
              className={styles.modalClose}
              onClick={onCloseMenu}
            >
              ×
            </button>
            <div className={styles.libraryTabs}>
              <strong>
                {t("aigcStudio.videoNode.effectSquare", "特效广场")}
              </strong>
              <span>{t("aigcStudio.videoNode.favorite", "我的收藏")}</span>
              <span>{t("aigcStudio.videoNode.recent", "最近使用")}</span>
            </div>
            <div className={styles.effectSearchRow}>
              <input
                type="search"
                aria-label={t(
                  "aigcStudio.videoNode.effectSearch",
                  "搜索特效名称、作者",
                )}
                placeholder={t(
                  "aigcStudio.videoNode.effectSearch",
                  "搜索特效名称、作者",
                )}
              />
              <span>Seedance 2.0</span>
            </div>
            <div className={styles.effectGrid}>
              {VIDEO_EFFECT_PRESETS.map((preset, index) => (
                <button
                  type="button"
                  key={preset}
                  className={
                    node.data.effectPreset === preset
                      ? styles.effectCardActive
                      : ""
                  }
                  onClick={() => {
                    onUpdateNodeData(node.id, { effectPreset: preset });
                  }}
                >
                  <span
                    className={
                      index % 3 === 0
                        ? styles.effectThumbDark
                        : index % 3 === 1
                        ? styles.effectThumbSky
                        : styles.effectThumbProduct
                    }
                  >
                    <Clapperboard size={18} />
                  </span>
                  <strong>{preset}</strong>
                  <small>{index % 2 === 0 ? "赛博蒲公英" : "数据星云"}</small>
                </button>
              ))}
            </div>
          </div>
        )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "motion" && (
          <div
            className={styles.motionLibrary}
            data-testid="aigc-video-motion-library"
          >
            <button
              type="button"
              className={styles.modalClose}
              onClick={onCloseMenu}
            >
              ×
            </button>
            <div className={styles.libraryTabs}>
              <strong>{t("aigcStudio.videoNode.preset", "预设")}</strong>
              <span>{t("aigcStudio.videoNode.custom", "自定义")}</span>
              <span>{t("aigcStudio.videoNode.favorite", "我的收藏")}</span>
            </div>
            <div className={styles.motionGrid}>
              {VIDEO_MOTION_PRESETS.map((preset, index) => (
                <button
                  type="button"
                  key={preset}
                  onClick={() => {
                    onUpdateNodeData(node.id, {
                      motionPreset: preset,
                    });
                  }}
                >
                  <span
                    className={
                      index % 3 === 0
                        ? styles.motionThumbClose
                        : styles.motionThumbWide
                    }
                  />
                  {preset}
                </button>
              ))}
            </div>
          </div>
        )}
      {videoComposerMenu?.nodeId === node.id &&
        videoComposerMenu.menu === "character" && (
          <div
            className={styles.characterLibrary}
            data-testid="aigc-video-character-library"
          >
            <button
              type="button"
              className={styles.modalClose}
              onClick={onCloseMenu}
            >
              ×
            </button>
            <div className={styles.characterHeader}>
              <strong>Seedance2.0合规素材库</strong>
              <span>
                {t("aigcStudio.videoNode.selected", "已选")}{" "}
                {characterAssetIds.length}/{MAX_VIDEO_CHARACTER_ASSETS} 张
              </span>
            </div>
            <div className={styles.libraryTabs}>
              {VIDEO_CHARACTER_TABS.map(([kind, label]) => (
                <button
                  type="button"
                  key={kind}
                  aria-label={t(`aigcStudio.videoNode.${kind}`, label)}
                  className={`${styles.libraryTabButton} ${
                    activeCharacterTab === kind ? styles.libraryTabActive : ""
                  } ${
                    kind === "real_person" ? styles.libraryTabWithBadge : ""
                  }`}
                  onClick={() => setActiveCharacterTab(kind)}
                >
                  {t(`aigcStudio.videoNode.${kind}`, label)}
                  {kind === "real_person" && <em>NEW</em>}
                </button>
              ))}
            </div>
            <div className={styles.characterUploadCard}>
              <button type="button">
                {t("aigcStudio.videoNode.localUpload", "本地上传")}
              </button>
              <button type="button">
                {t("aigcStudio.videoNode.historyAsset", "历史资产选择")}
              </button>
              <button type="button">
                {t("aigcStudio.videoNode.realPersonAsset", "真人资产录入")}
              </button>
              <small>
                {t("aigcStudio.videoNode.uploadHint", "请上传<30M的图片")}
              </small>
            </div>
            <div className={styles.characterAssetGrid}>
              {visibleCharacterAssets.map((asset) => {
                const selected = characterAssetIds.includes(asset.id);
                const disabled =
                  !selected &&
                  characterAssetIds.length >= MAX_VIDEO_CHARACTER_ASSETS;
                return (
                  <button
                    type="button"
                    key={asset.id}
                    aria-label={asset.name}
                    aria-disabled={disabled}
                    aria-pressed={selected}
                    className={`${
                      selected ? styles.characterAssetActive : ""
                    } ${disabled ? styles.characterAssetDisabled : ""}`}
                    onClick={() => toggleCharacterAsset(asset.id, asset.name)}
                  >
                    <span
                      className={
                        asset.tone === "product"
                          ? styles.characterThumbProduct
                          : asset.tone === "portrait"
                          ? styles.characterThumbPortrait
                          : asset.tone === "landscape"
                          ? styles.characterThumbLandscape
                          : styles.characterThumbStore
                      }
                    />
                    <strong>{asset.name}</strong>
                    <small>
                      {asset.kind === "real_person"
                        ? t("aigcStudio.videoNode.realPerson", "真人像")
                        : asset.kind === "video"
                        ? t("aigcStudio.videoNode.video", "视频")
                        : asset.kind === "audio"
                        ? t("aigcStudio.videoNode.audio", "音频")
                        : t("aigcStudio.videoNode.image", "图片")}
                    </small>
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className={styles.characterConfirm}
              onClick={onCloseMenu}
            >
              {t("common.ok", "确定")}
            </button>
          </div>
        )}
      <PromptFullscreenEditor
        open={composerFullscreenOpen}
        title={t(
          "aigcStudio.videoNode.composerFullscreenTitle",
          "视频节点输入全屏编辑",
        )}
        label={t(
          "aigcStudio.videoNode.composerFullscreenLabel",
          "视频节点输入全屏编辑",
        )}
        value={composerDraftText}
        placeholder={videoComposerPlaceholder}
        closeLabel={t("aigcStudio.composer.fullscreen.close", "关闭全屏编辑")}
        meta={t("aigcStudio.composer.fullscreen.meta", "{{count}} 字", {
          count: composerDraftText.length,
        })}
        onChange={updateComposerText}
        onClose={() => setComposerFullscreenOpen(false)}
      />
    </div>
  );
}
