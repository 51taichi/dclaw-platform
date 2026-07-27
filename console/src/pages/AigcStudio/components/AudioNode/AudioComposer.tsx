import { useEffect, useRef, useState } from "react";
import {
  AudioLines,
  AudioWaveform,
  ChevronDown,
  Languages,
  Maximize2,
  Mic,
  Play,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import styles from "../../index.module.less";
import { PromptFullscreenEditor } from "../PromptFullscreenEditor";
import { useAutoGrowTextarea } from "../useAutoGrowTextarea";
import {
  AUDIO_EFFECT_OPTIONS,
  AUDIO_FILLER_OPTIONS,
  AUDIO_PAUSE_OPTIONS,
  AUDIO_VOICE_OPTIONS,
  DEFAULT_AUDIO_MODEL_LABEL,
  DEFAULT_AUDIO_VOICE_ID,
  DEFAULT_AUDIO_VOICE_NAME,
} from "./audioNodeState";
import type { AudioComposerProps } from "./types";

type AudioComposerMenu = "pause" | "filler" | "voice" | "tuning" | null;
type VoiceGenderFilter = "all" | "Male" | "Female";

const MAX_AUDIO_TEXT_LENGTH = 50000;
const CUSTOM_PAUSE_LABEL = "自定义";
const DEFAULT_CUSTOM_PAUSE_SECONDS = "0.25";
const VOICE_GENDER_FILTERS: Array<{
  id: VoiceGenderFilter;
  label: string;
}> = [
  { id: "all", label: "全部" },
  { id: "Male", label: "男声" },
  { id: "Female", label: "女声" },
];

const numberValue = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

const appendToken = (text: string, token: string) =>
  `${text.trimEnd()}${text.trim() ? " " : ""}${token}`;

const formatPauseSeconds = (value: string) => {
  const numericValue = Number(value);
  const safeValue = Number.isFinite(numericValue)
    ? Math.min(Math.max(numericValue, 0.1), 10)
    : Number(DEFAULT_CUSTOM_PAUSE_SECONDS);
  return safeValue.toFixed(2).replace(/\.?0+$/, "");
};

const customPauseToken = (value: string) => `<#${formatPauseSeconds(value)}#>`;

export function AudioComposer({
  node,
  currentModel,
  modelOptions,
  t,
  workflow,
  disabled,
  onUpdateNodeData,
  onRunNode,
}: AudioComposerProps) {
  const [activeMenu, setActiveMenu] = useState<AudioComposerMenu>(null);
  const [showCustomPause, setShowCustomPause] = useState(false);
  const [customPauseSeconds, setCustomPauseSeconds] = useState(
    DEFAULT_CUSTOM_PAUSE_SECONDS,
  );
  const [voiceSearch, setVoiceSearch] = useState("");
  const [voiceGenderFilter, setVoiceGenderFilter] =
    useState<VoiceGenderFilter>("all");
  const [previewVoiceId, setPreviewVoiceId] = useState<string | null>(null);
  const [composerFullscreenOpen, setComposerFullscreenOpen] = useState(false);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const selectedAudioModel =
    currentModel && currentModel.capability.includes("audio")
      ? currentModel
      : null;
  const firstAudioModel = modelOptions.find((model) =>
    model.capability.includes("audio"),
  );
  const modelLabel = String(
    node.data.modelLabel ??
      selectedAudioModel?.model_name ??
      selectedAudioModel?.model_id ??
      firstAudioModel?.model_name ??
      firstAudioModel?.model_id ??
      node.data.title ??
      DEFAULT_AUDIO_MODEL_LABEL,
  );
  const composerTextValue = String(
    node.data.composerText ?? node.data.text ?? "",
  );
  const [composerDraftText, setComposerDraftText] = useState(composerTextValue);
  const composerNodeIdRef = useRef(node.id);
  const composerTextValueRef = useRef(composerTextValue);
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
  const composerText = composerDraftText;
  useAutoGrowTextarea(composerText, composerInputRef);
  const audioVoiceId = String(node.data.audioVoiceId ?? DEFAULT_AUDIO_VOICE_ID);
  const audioVoiceName = String(
    node.data.audioVoiceName ?? DEFAULT_AUDIO_VOICE_NAME,
  );
  const speechRate = numberValue(node.data.speechRate, 1);
  const speechPitch = numberValue(node.data.speechPitch, 0);
  const speechVolume = numberValue(node.data.speechVolume, 1);
  const speechTone = numberValue(node.data.speechTone, 0);
  const speechStrength = numberValue(node.data.speechStrength, 0);
  const speechTimbre = numberValue(node.data.speechTimbre, 0);
  const soundEffect = String(node.data.soundEffect ?? "无");
  const normalizedVoiceSearch = voiceSearch.trim().toLowerCase();
  const filteredVoiceOptions = AUDIO_VOICE_OPTIONS.filter((voice) => {
    const matchesGender =
      voiceGenderFilter === "all" || voice.gender === voiceGenderFilter;
    const matchesSearch =
      !normalizedVoiceSearch ||
      `${voice.name} ${voice.locale} ${voice.gender}`
        .toLowerCase()
        .includes(normalizedVoiceSearch);
    return matchesGender && matchesSearch;
  });
  const previewVoice = AUDIO_VOICE_OPTIONS.find(
    (voice) => voice.id === previewVoiceId,
  );

  const audioComposerPlaceholder = t(
    "aigcStudio.audioNode.composerPlaceholder",
    "输入要合成的文本",
  );
  const updateAudioText = (value: string) => {
    const nextText = value.slice(0, MAX_AUDIO_TEXT_LENGTH);
    setComposerDraftText(nextText);
    onUpdateNodeData(node.id, {
      composerText: nextText,
    });
  };
  const insertAudioToken = (token: string, data: Record<string, unknown>) => {
    const nextText = appendToken(composerText, token);
    setComposerDraftText(nextText);
    onUpdateNodeData(node.id, {
      ...data,
      composerText: nextText,
    });
    setActiveMenu(null);
    setShowCustomPause(false);
  };
  const updateTuningValue = (key: string, value: number) => {
    onUpdateNodeData(node.id, { [key]: value });
  };
  const handlePauseOption = (option: (typeof AUDIO_PAUSE_OPTIONS)[number]) => {
    if (option.label === CUSTOM_PAUSE_LABEL) {
      setShowCustomPause(true);
      return;
    }
    insertAudioToken(option.token, {
      audioPauseTag: option.token,
    });
  };
  const handleInsertCustomPause = () => {
    const token = customPauseToken(customPauseSeconds);
    insertAudioToken(token, { audioPauseTag: token });
  };

  return (
    <div
      className={styles.audioComposer}
      data-testid="aigc-audio-composer"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className={styles.composerExpand}
        aria-label={t("aigcStudio.composer.fullscreen.open", "全屏编辑输入")}
        onClick={() => setComposerFullscreenOpen(true)}
      >
        <Maximize2 size={15} />
      </button>
      <textarea
        ref={composerInputRef}
        className={`${styles.promptPlaceholder} ${styles.textComposerInput} ${styles.audioComposerInput}`}
        value={composerText}
        placeholder={audioComposerPlaceholder}
        aria-label={t("aigcStudio.audioNode.composerLabel", "音频节点输入")}
        maxLength={MAX_AUDIO_TEXT_LENGTH}
        onMouseDown={() => setActiveMenu(null)}
        onFocus={() => setActiveMenu(null)}
        onChange={(event) => updateAudioText(event.target.value)}
      />
      <div className={styles.audioTagRow}>
        <button
          type="button"
          className={node.data.audioPauseTag ? styles.imageToolActive : ""}
          aria-label={t("aigcStudio.audioNode.pause", "停顿")}
          onClick={() => {
            setActiveMenu(activeMenu === "pause" ? null : "pause");
            setShowCustomPause(false);
          }}
        >
          &lt;#&gt; {t("aigcStudio.audioNode.pause", "停顿")}
        </button>
        <button
          type="button"
          className={node.data.audioFillerTag ? styles.imageToolActive : ""}
          aria-label={t("aigcStudio.audioNode.filler", "语气词")}
          onClick={() =>
            setActiveMenu(activeMenu === "filler" ? null : "filler")
          }
        >
          () {t("aigcStudio.audioNode.filler", "语气词")}
        </button>
      </div>
      {activeMenu === "pause" && (
        <div
          className={`${styles.audioTokenMenu} ${
            showCustomPause ? styles.audioTokenMenuWide : ""
          }`}
          data-testid="aigc-audio-pause-menu"
        >
          {AUDIO_PAUSE_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.label}
              className={
                node.data.audioPauseTag === option.token
                  ? styles.textModelActive
                  : ""
              }
              onClick={() => handlePauseOption(option)}
            >
              {option.label}
            </button>
          ))}
          {showCustomPause && (
            <div
              className={styles.audioCustomPauseRow}
              data-testid="aigc-audio-custom-pause"
            >
              <label>
                <span>{t("aigcStudio.audioNode.pauseSeconds", "秒")}</span>
                <input
                  aria-label={t(
                    "aigcStudio.audioNode.customPauseSeconds",
                    "自定义停顿秒数",
                  )}
                  type="number"
                  min={0.1}
                  max={10}
                  step={0.05}
                  value={customPauseSeconds}
                  onChange={(event) =>
                    setCustomPauseSeconds(event.target.value)
                  }
                />
              </label>
              <button type="button" onClick={handleInsertCustomPause}>
                {t("aigcStudio.audioNode.insertPause", "插入停顿")}
              </button>
            </div>
          )}
        </div>
      )}
      {activeMenu === "filler" && (
        <div
          className={styles.audioTokenMenu}
          data-testid="aigc-audio-filler-menu"
        >
          {AUDIO_FILLER_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.label}
              className={
                node.data.audioFillerTag === option.token
                  ? styles.textModelActive
                  : ""
              }
              onClick={() =>
                insertAudioToken(option.token, {
                  audioFillerTag: option.token,
                })
              }
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
      <div className={styles.parameterBar}>
        <button type="button" className={styles.textModelButton}>
          <AudioWaveform size={14} />
          {modelLabel}
          <ChevronDown size={13} />
        </button>
        <button
          type="button"
          className={styles.textModelButton}
          aria-label={t("aigcStudio.audioNode.selectVoice", "选择音色")}
          onClick={() => setActiveMenu(activeMenu === "voice" ? null : "voice")}
        >
          <AudioLines size={14} />
          {audioVoiceName}
          <ChevronDown size={13} />
        </button>
        <button
          type="button"
          className={styles.iconParamButton}
          aria-label={t("aigcStudio.audioNode.translatePrompt", "翻译提示词")}
        >
          <Languages size={15} />
        </button>
        <button
          type="button"
          className={styles.iconParamButton}
          aria-label={t("aigcStudio.audioNode.tuning", "音频参数调节")}
          onClick={() =>
            setActiveMenu(activeMenu === "tuning" ? null : "tuning")
          }
        >
          <SlidersHorizontal size={15} />
        </button>
        <span>
          {composerText.length}/{MAX_AUDIO_TEXT_LENGTH}
        </span>
        <span>✦ {Number(node.data.audioCount ?? 1)}</span>
        <button
          type="button"
          className={styles.runCircle}
          aria-label={t(
            "aigcStudio.audioNode.submitComposer",
            "提交音频节点输入",
          )}
          onClick={(event) => {
            const nodeSnapshot = workflow.handleAudioComposerSubmit({
              ...node,
              data: {
                ...node.data,
                composerText,
              },
            });
            onRunNode(event, nodeSnapshot);
          }}
          disabled={disabled}
        >
          <Play size={15} />
        </button>
      </div>
      {activeMenu === "voice" && (
        <div
          className={styles.audioVoicePanel}
          data-testid="aigc-audio-voice-panel"
        >
          <div className={styles.audioPanelHeader}>
            <strong>{t("aigcStudio.audioNode.voicePanel", "音色选择")}</strong>
            <button
              type="button"
              onClick={() => setActiveMenu(null)}
              aria-label={t("aigcStudio.close", "关闭")}
            >
              ×
            </button>
          </div>
          <div className={styles.audioVoiceTabs}>
            <strong>{t("aigcStudio.audioNode.voiceLibrary", "音色库")}</strong>
            <span>{t("aigcStudio.audioNode.myVoice", "我的音色")}</span>
            <span>{t("aigcStudio.audioNode.favoriteVoice", "收藏音色")}</span>
            <button type="button">
              <Mic size={14} />
              {t("aigcStudio.audioNode.cloneVoice", "克隆新音色")}
            </button>
          </div>
          <div className={styles.audioVoiceFilters}>
            <label>
              <Search size={14} />
              <input
                aria-label={t(
                  "aigcStudio.audioNode.searchVoiceLibrary",
                  "搜索音色库",
                )}
                value={voiceSearch}
                placeholder={t(
                  "aigcStudio.audioNode.searchVoicePlaceholder",
                  "搜索音色名称、语言或性别",
                )}
                onChange={(event) => setVoiceSearch(event.target.value)}
              />
            </label>
            <div>
              {VOICE_GENDER_FILTERS.map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  aria-pressed={voiceGenderFilter === filter.id}
                  onClick={() => setVoiceGenderFilter(filter.id)}
                >
                  {t(
                    `aigcStudio.audioNode.voiceFilter.${filter.id}`,
                    filter.label,
                  )}
                </button>
              ))}
            </div>
          </div>
          {previewVoice && (
            <span className={styles.audioVoicePreviewStatus}>
              {t(
                "aigcStudio.audioNode.previewingVoice",
                "正在试听 {{voiceName}}",
                {
                  voiceName: previewVoice.name,
                },
              )}
            </span>
          )}
          <div className={styles.audioVoiceList}>
            {filteredVoiceOptions.length === 0 ? (
              <div className={styles.audioVoiceEmpty}>
                {t("aigcStudio.audioNode.noVoiceMatch", "没有匹配音色")}
              </div>
            ) : (
              filteredVoiceOptions.map((voice) => (
                <div
                  key={voice.id}
                  className={
                    audioVoiceId === voice.id
                      ? styles.audioVoiceSelected
                      : undefined
                  }
                >
                  <span>
                    <AudioLines size={16} />
                  </span>
                  <strong>{voice.name}</strong>
                  <small>{voice.locale}</small>
                  <small>{voice.gender}</small>
                  <button
                    type="button"
                    aria-label={`试听 ${voice.name}`}
                    aria-pressed={previewVoiceId === voice.id}
                    className={styles.audioVoicePreviewButton}
                    onClick={() => setPreviewVoiceId(voice.id)}
                  >
                    <Play size={12} />
                    {previewVoiceId === voice.id
                      ? t("aigcStudio.audioNode.previewing", "试听中")
                      : t("aigcStudio.audioNode.preview", "试听")}
                  </button>
                  <button
                    type="button"
                    aria-label={`选择 ${voice.name}`}
                    onClick={() => {
                      onUpdateNodeData(node.id, {
                        audioVoiceId: voice.id,
                        audioVoiceName: voice.name,
                      });
                      setActiveMenu(null);
                    }}
                  >
                    {audioVoiceId === voice.id
                      ? t("aigcStudio.videoNode.selected", "已选")
                      : t("aigcStudio.imageNode.use", "使用")}
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
      {activeMenu === "tuning" && (
        <div
          className={styles.audioTuningPanel}
          data-testid="aigc-audio-tuning-panel"
        >
          <div className={styles.audioPanelHeader}>
            <strong>{t("aigcStudio.audioNode.basicTuning", "基础调节")}</strong>
            <button
              type="button"
              onClick={() =>
                onUpdateNodeData(node.id, {
                  speechRate: 1,
                  speechPitch: 0,
                  speechVolume: 1,
                  speechTone: 0,
                  speechStrength: 0,
                  speechTimbre: 0,
                  soundEffect: "无",
                })
              }
            >
              {t("aigcStudio.audioNode.reset", "一键重置")}
            </button>
          </div>
          <label>
            {t("aigcStudio.audioNode.speechRate", "语速")}
            <input
              type="range"
              aria-label={t("aigcStudio.audioNode.speechRate", "语速")}
              min="0.5"
              max="2"
              step="0.01"
              value={speechRate}
              onChange={(event) =>
                updateTuningValue("speechRate", Number(event.target.value))
              }
            />
            <span>{speechRate.toFixed(2)}</span>
          </label>
          <label>
            {t("aigcStudio.audioNode.pitch", "声调")}
            <input
              type="range"
              aria-label={t("aigcStudio.audioNode.pitch", "声调")}
              min="-12"
              max="12"
              value={speechPitch}
              onChange={(event) =>
                updateTuningValue("speechPitch", Number(event.target.value))
              }
            />
            <span>{speechPitch}</span>
          </label>
          <label>
            {t("aigcStudio.audioNode.volume", "音量")}
            <input
              type="range"
              aria-label={t("aigcStudio.audioNode.volume", "音量")}
              min="0"
              max="2"
              step="0.01"
              value={speechVolume}
              onChange={(event) =>
                updateTuningValue("speechVolume", Number(event.target.value))
              }
            />
            <span>{speechVolume.toFixed(2)}</span>
          </label>
          <div className={styles.audioTuningGroup}>
            <strong>
              {t("aigcStudio.audioNode.effectTuning", "音色效果调节")}
            </strong>
            <label>
              {t("aigcStudio.audioNode.tone", "音高")}
              <input
                type="range"
                aria-label={t("aigcStudio.audioNode.tone", "音高")}
                min="-10"
                max="10"
                value={speechTone}
                onChange={(event) =>
                  updateTuningValue("speechTone", Number(event.target.value))
                }
              />
              <span>{speechTone}</span>
            </label>
            <label>
              {t("aigcStudio.audioNode.strength", "强度")}
              <input
                type="range"
                aria-label={t("aigcStudio.audioNode.strength", "强度")}
                min="-10"
                max="10"
                value={speechStrength}
                onChange={(event) =>
                  updateTuningValue(
                    "speechStrength",
                    Number(event.target.value),
                  )
                }
              />
              <span>{speechStrength}</span>
            </label>
            <label>
              {t("aigcStudio.audioNode.timbre", "音色调节")}
              <input
                type="range"
                aria-label={t("aigcStudio.audioNode.timbre", "音色调节")}
                min="-10"
                max="10"
                step="0.1"
                value={speechTimbre}
                onChange={(event) =>
                  updateTuningValue("speechTimbre", Number(event.target.value))
                }
              />
              <span>{speechTimbre}</span>
            </label>
          </div>
          <div className={styles.audioEffectOptions}>
            {AUDIO_EFFECT_OPTIONS.map((effect) => (
              <button
                type="button"
                key={effect}
                aria-pressed={soundEffect === effect}
                className={
                  soundEffect === effect ? styles.imageOptionActive : ""
                }
                onClick={() => {
                  onUpdateNodeData(node.id, { soundEffect: effect });
                  setActiveMenu(null);
                }}
              >
                {effect}
              </button>
            ))}
          </div>
        </div>
      )}
      <PromptFullscreenEditor
        open={composerFullscreenOpen}
        title={t(
          "aigcStudio.audioNode.composerFullscreenTitle",
          "音频节点输入全屏编辑",
        )}
        label={t(
          "aigcStudio.audioNode.composerFullscreenTitle",
          "音频节点输入全屏编辑",
        )}
        value={composerText}
        placeholder={audioComposerPlaceholder}
        closeLabel={t("aigcStudio.composer.fullscreen.close", "关闭全屏编辑")}
        meta={t("aigcStudio.composer.fullscreen.meta", "{{count}} 字", {
          count: composerText.length,
        })}
        onChange={updateAudioText}
        onClose={() => setComposerFullscreenOpen(false)}
      />
    </div>
  );
}
