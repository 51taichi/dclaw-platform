import { useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  Loader2,
  MoreHorizontal,
  Plus,
  Sparkles,
  X,
  Zap,
} from "lucide-react";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import {
  DEFAULT_IMAGE_QUALITY,
  DEFAULT_IMAGE_RESOLUTION,
  IMAGE_QUALITY_OPTIONS,
  imageModelDisplayName,
  imageModelOptionsFrom,
} from "../ImageNode/imageNodeState";
import {
  imageModelParameterProfileFor,
  normalizedImageParameterSelection,
} from "../ImageNode/imageModelParameterProfile";
import {
  SCRIPT_STORY_TITLE,
  scriptMode,
  scriptSelectedShotIds,
  scriptShotsFromNode,
  scriptWorkflowStep,
  type ScriptShot,
  type ScriptWorkflowStep,
} from "./scriptNodeState";
import type {
  ScriptNodeWorkflow,
  StoryboardWorkflow,
  Translate,
} from "./types";

type ScriptResultPanelProps = {
  node: AigcCanvasNode;
  t: Translate;
  modelOptions?: AigcCapabilityInfo[];
  scriptWorkflow: ScriptNodeWorkflow;
  storyboardWorkflow: StoryboardWorkflow;
};

type ScriptAssetGroups = {
  characters: string[];
  scenes: string[];
  props: string[];
};

type ScriptAssetKind = "character" | "scene" | "prop";
type ScriptAssetStatus = "idle" | "generating" | "ready" | "uploaded";
type ScriptPromptStatus = "idle" | "generating" | "ready";

type ScriptAssetItem = {
  id: string;
  kind: ScriptAssetKind;
  label: string;
  description: string;
  status: ScriptAssetStatus;
};

const panelTextValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const WORKBENCH_STEPS: Array<{
  value: ScriptWorkflowStep;
  label: string;
}> = [
  { value: "shots", label: "确认镜头" },
  { value: "assets", label: "准备资产" },
  { value: "prompts", label: "合成提示词" },
];

type ScriptAssetDialogMenu = "model" | "quality" | "resolution" | "ratio";

type ScriptAssetModelOption = {
  key: string;
  label: string;
  model?: AigcCapabilityInfo;
};

const FALLBACK_SCRIPT_ASSET_MODELS: ScriptAssetModelOption[] = [
  "Lib Image",
  "Lib Navo Pro",
  "Lib Navo 2",
  "悠船 V8.1",
  "悠船 V7",
  "悠船 Niji 7",
  "Seedream 4.6",
  "Seedream 5.0 Lite",
  "Seedream 4.5",
].map((label) => ({
  key: `fallback:${label}`,
  label,
}));

const HORIZONTAL_ASPECT_RATIO_PRIORITY = ["2:1", "16:9", "3:2", "21:9"];

function scriptAssetModelOptionsFrom(
  modelOptions: AigcCapabilityInfo[] | undefined,
): ScriptAssetModelOption[] {
  const imageModels = imageModelOptionsFrom(modelOptions ?? []);
  if (!imageModels.length) return FALLBACK_SCRIPT_ASSET_MODELS;
  return imageModels.map((model) => ({
    key: `${model.provider_id}:${model.model_id}`,
    label: imageModelDisplayName(model.model_name) || model.model_id,
    model,
  }));
}

function preferredScriptAssetAspectRatio(ratios: string[]) {
  return (
    HORIZONTAL_ASPECT_RATIO_PRIORITY.find((ratio) => ratios.includes(ratio)) ??
    ratios[0] ??
    "2:1"
  );
}

function scriptAssetRatioOptions(ratios: string[]) {
  const horizontal = HORIZONTAL_ASPECT_RATIO_PRIORITY.filter((ratio) =>
    ratios.includes(ratio),
  );
  return horizontal.length ? horizontal : ratios;
}

function preferredScriptAssetResolution(resolutions: string[]) {
  return resolutions.includes(DEFAULT_IMAGE_RESOLUTION)
    ? DEFAULT_IMAGE_RESOLUTION
    : resolutions[0] ?? DEFAULT_IMAGE_RESOLUTION;
}

const EMPTY_SCRIPT_ASSET_LABELS = new Set([
  "-",
  "无",
  "暂无",
  "没有",
  "无角色",
  "无人物",
  "无道具",
  "无明显道具",
  "无场景",
  "无特定场景",
  "不涉及",
  "none",
  "null",
  "n/a",
]);

const PLACEHOLDER_SCRIPT_ASSET_LABELS = new Set([
  "主要角色",
  "主要场景",
  "关键道具",
]);

function normalizedScriptAssetLabel(value: string) {
  return value.trim().replace(/\s+/g, "").toLowerCase();
}

function isUsableScriptAssetLabel(value: string) {
  const normalized = normalizedScriptAssetLabel(value);
  return (
    Boolean(normalized) &&
    !EMPTY_SCRIPT_ASSET_LABELS.has(normalized) &&
    !PLACEHOLDER_SCRIPT_ASSET_LABELS.has(normalized)
  );
}

function uniqueNonEmpty(values: Array<string | undefined>) {
  return Array.from(
    new Set(
      values
        .map((value) => value?.trim())
        .filter(
          (value): value is string =>
            value !== undefined &&
            value.length > 0 &&
            isUsableScriptAssetLabel(value),
        ),
    ),
  );
}

function assetGroupsFromShots(shots: ScriptShot[]): ScriptAssetGroups {
  const characters = uniqueNonEmpty(
    shots.flatMap((shot) => [shot.character, shot.character2]),
  ).slice(0, 4);
  const scenes = uniqueNonEmpty(shots.map((shot) => shot.scene)).slice(0, 4);
  const props = uniqueNonEmpty(
    shots.map((shot) => {
      if (shot.imageDescription.includes("刀")) return "刀具";
      if (shot.imageDescription.includes("屏幕")) return "屏幕";
      if (shot.imageDescription.includes("龙椅")) return "龙椅";
      if (shot.imageDescription.includes("衣袖")) return "衣袖";
      return undefined;
    }),
  ).slice(0, 4);
  return {
    characters,
    scenes,
    props,
  };
}

function scriptAssetStatesFromNode(node: AigcCanvasNode) {
  const states = node.data.scriptAssetStates;
  if (!states || typeof states !== "object" || Array.isArray(states)) {
    return {};
  }
  return states as Record<string, ScriptAssetStatus>;
}

function scriptPromptStatesFromNode(node: AigcCanvasNode) {
  const states = node.data.scriptPromptStates;
  if (!states || typeof states !== "object" || Array.isArray(states)) {
    return {};
  }
  return states as Record<string, ScriptPromptStatus>;
}

function isScriptAssetReady(asset: ScriptAssetItem) {
  return asset.status === "ready" || asset.status === "uploaded";
}

function isScriptPromptReady(status: ScriptPromptStatus) {
  return status === "ready";
}

function scriptPromptStatusForShot(
  states: Record<string, ScriptPromptStatus>,
  shotId: string,
): ScriptPromptStatus {
  return states[shotId] === "ready" || states[shotId] === "generating"
    ? states[shotId]
    : "idle";
}

function scriptAssetsFromGroups(
  node: AigcCanvasNode,
  groups: ScriptAssetGroups,
) {
  const states = scriptAssetStatesFromNode(node);
  const build = (
    kind: ScriptAssetKind,
    label: string,
    description: string,
  ): ScriptAssetItem => {
    const id = `${kind}:${label}`;
    return {
      id,
      kind,
      label,
      description,
      status:
        states[id] === "ready" ||
        states[id] === "uploaded" ||
        states[id] === "generating"
          ? states[id]
          : "idle",
    };
  };

  return [
    ...groups.characters.map((label) =>
      build("character", label, `角色形象：${label}`),
    ),
    ...groups.scenes.map((label) =>
      build("scene", label, `场景资产：${label}`),
    ),
    ...groups.props.map((label) => build("prop", label, `关键道具：${label}`)),
  ];
}

function ScriptWorkbenchHeader({
  node,
  t,
  scriptWorkflow,
  shots,
  assets,
}: ScriptResultPanelProps & {
  shots: ScriptShot[];
  assets: ScriptAssetItem[];
}) {
  const activeStep = scriptWorkflowStep(node);
  const activeIndex = WORKBENCH_STEPS.findIndex(
    (step) => step.value === activeStep,
  );
  const generatedAssets = assets.filter(isScriptAssetReady).length;
  const totalAssets = assets.length;
  const allAssetsReady = totalAssets > 0 && generatedAssets === totalAssets;
  const promptStates = scriptPromptStatesFromNode(node);
  const generatedPrompts = shots.filter((shot) =>
    isScriptPromptReady(scriptPromptStatusForShot(promptStates, shot.id)),
  ).length;
  const allPromptsReady = shots.length > 0 && generatedPrompts === shots.length;
  const completedStageCount = allPromptsReady ? 3 : allAssetsReady ? 2 : 1;
  const metaByStep: Record<ScriptWorkflowStep, string> = {
    shots: t(
      "aigcStudio.scriptNode.workbench.shotProgress",
      "{{count}}个镜头已就绪",
      { count: shots.length },
    ),
    assets: t(
      "aigcStudio.scriptNode.workbench.assetProgress",
      generatedAssets === totalAssets
        ? "{{ready}}/{{count}} 已生成"
        : "{{ready}}/{{count}} 已生成，还差 {{remaining}} 个",
      {
        count: totalAssets,
        ready: generatedAssets,
        remaining: totalAssets - generatedAssets,
      },
    ),
    prompts: t(
      "aigcStudio.scriptNode.workbench.promptProgress",
      "{{ready}}/{{count}} 已合成",
      { count: shots.length, ready: generatedPrompts },
    ),
  };

  return (
    <header className={styles.scriptWorkbenchHeader}>
      <div className={styles.scriptWorkbenchTopline}>
        <strong>{String(node.data.scriptPrompt ?? SCRIPT_STORY_TITLE)}</strong>
        <div className={styles.scriptWorkbenchMeta}>
          <span>
            {t(
              "aigcStudio.scriptNode.workbench.batchVideoHint",
              "{{count}}/3 完成后可批量生视频",
              { count: completedStageCount },
            )}
          </span>
          <button
            type="button"
            aria-label={t("aigcStudio.scriptNode.exitFullscreen", "退出放大")}
            onClick={(event) => {
              event.stopPropagation();
              scriptWorkflow.handleToggleScriptFullscreen(node);
            }}
          >
            <X size={16} />
          </button>
        </div>
      </div>
      <div
        className={styles.scriptWorkbenchStepper}
        data-testid="aigc-script-workbench-stepper"
      >
        {WORKBENCH_STEPS.map((step, index) => {
          const completed = index < activeIndex;
          const active = step.value === activeStep;
          return (
            <button
              type="button"
              key={step.value}
              className={[
                styles.scriptWorkbenchStepButton,
                active ? styles.scriptWorkbenchStepActive : "",
                completed ? styles.scriptWorkbenchStepComplete : "",
              ].join(" ")}
              onClick={(event) => {
                event.stopPropagation();
                scriptWorkflow.handleScriptWorkflowStepChange(node, step.value);
              }}
            >
              <span className={styles.scriptWorkbenchStepIndex}>
                {completed ? <CheckCircle2 size={16} /> : index + 1}
              </span>
              <span>
                <strong>{step.label}</strong>
                <em>{metaByStep[step.value]}</em>
              </span>
            </button>
          );
        })}
      </div>
      <div className={styles.scriptGlobalStyle}>
        <strong>
          {t("aigcStudio.scriptNode.workbench.globalStyle", "全局风格")}
        </strong>
        <span>
          {t(
            "aigcStudio.scriptNode.workbench.globalStyleValue",
            "现代都市惊悚·电影级写实 | 幽暗冷青色调，局部暖红光点缀，高对比度",
          )}
        </span>
      </div>
    </header>
  );
}

function ScriptShotTable({
  node,
  selectable,
  t,
  storyboardWorkflow,
  shots,
  promptStates,
  promptProgress,
  onViewPrompt,
}: ScriptResultPanelProps & {
  selectable: boolean;
  shots: ScriptShot[];
  promptStates?: Record<string, ScriptPromptStatus>;
  promptProgress?: number;
  onViewPrompt?: (shot: ScriptShot) => void;
}) {
  const selected = new Set(scriptSelectedShotIds(node));
  const allSelected = shots.length > 0 && selected.size === shots.length;
  const showPromptActions = Boolean(promptStates && onViewPrompt);
  return (
    <div
      className={styles.scriptWorkbenchTableWrap}
      data-testid="aigc-script-table"
    >
      <table className={styles.scriptWorkbenchTable}>
        <thead>
          <tr>
            {selectable && (
              <th className={styles.scriptCheckCell}>
                <input
                  type="checkbox"
                  aria-label={t(
                    "aigcStudio.scriptNode.selectAll",
                    "选择全部镜号",
                  )}
                  checked={allSelected}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) =>
                    storyboardWorkflow.handleToggleAllScriptShots(
                      node,
                      event.target.checked,
                    )
                  }
                />
              </th>
            )}
            <th>{t("aigcStudio.scriptNode.columns.shot", "镜号")}</th>
            <th>{t("aigcStudio.scriptNode.columns.duration", "时长")}</th>
            <th>{t("aigcStudio.scriptNode.columns.image", "画面描述")}</th>
            <th>{t("aigcStudio.scriptNode.columns.shotType", "景别")}</th>
            <th>
              {t("aigcStudio.scriptNode.columns.lightingMood", "光影氛围")}
            </th>
            <th>{t("aigcStudio.scriptNode.columns.dialogue", "对白-旁白")}</th>
            <th>{t("aigcStudio.scriptNode.columns.soundEffect", "音效")}</th>
            <th>{t("aigcStudio.scriptNode.columns.cameraMove", "运镜")}</th>
            <th>
              {t("aigcStudio.scriptNode.columns.finalPrompt", "最终提示词")}
            </th>
            <th>{t("aigcStudio.scriptNode.columns.operation", "操作")}</th>
          </tr>
        </thead>
        <tbody>
          {shots.map((shot) => (
            <tr key={shot.id}>
              {selectable && (
                <td className={styles.scriptCheckCell}>
                  <input
                    type="checkbox"
                    aria-label={t(
                      "aigcStudio.scriptNode.selectShot",
                      "选择镜号 {{no}}",
                      { no: shot.no },
                    )}
                    checked={selected.has(shot.id)}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) =>
                      storyboardWorkflow.handleToggleScriptShot(
                        node,
                        shot.id,
                        event.target.checked,
                      )
                    }
                  />
                </td>
              )}
              <td>{shot.no}</td>
              <td>{shot.duration}s</td>
              <td>{shot.imageDescription}</td>
              <td>{shot.shotType}</td>
              <td>{shot.lightingMood ?? shot.sceneMood ?? shot.prompt}</td>
              <td>{shot.dialogue}</td>
              <td>
                {shot.soundEffect ??
                  t("aigcStudio.scriptNode.noSound", "环境声")}
              </td>
              <td>{shot.camera ?? shot.videoPrompt}</td>
              <td>
                {showPromptActions &&
                scriptPromptStatusForShot(promptStates ?? {}, shot.id) ===
                  "ready" ? (
                  <button
                    type="button"
                    className={styles.scriptPromptViewButton}
                    onClick={(event) => {
                      event.stopPropagation();
                      onViewPrompt?.(shot);
                    }}
                  >
                    {t(
                      "aigcStudio.scriptNode.prompts.viewPrompt",
                      "查看提示词",
                    )}
                  </button>
                ) : showPromptActions &&
                  scriptPromptStatusForShot(promptStates ?? {}, shot.id) ===
                    "generating" ? (
                  <span className={styles.scriptPromptGenerating}>
                    <Loader2 size={13} />
                    {t(
                      "aigcStudio.scriptNode.prompts.generating",
                      "合成中 {{progress}}%",
                      { progress: Number(promptProgress ?? 3) },
                    )}
                  </span>
                ) : (
                  <span className={styles.scriptPendingPrompt}>
                    {t("aigcStudio.scriptNode.pendingPrompt", "待生成提示词")}
                  </span>
                )}
              </td>
              <td>
                <button
                  type="button"
                  className={styles.scriptRowAction}
                  aria-label={t(
                    "aigcStudio.scriptNode.moreShotActions",
                    "更多镜头操作",
                  )}
                  onClick={(event) => event.stopPropagation()}
                >
                  <MoreHorizontal size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScriptShotsStep({
  node,
  t,
  scriptWorkflow,
  storyboardWorkflow,
  shots,
}: ScriptResultPanelProps & {
  shots: ScriptShot[];
}) {
  return (
    <>
      <ScriptShotTable
        node={node}
        selectable={scriptMode(node) === "storyboard_select"}
        t={t}
        scriptWorkflow={scriptWorkflow}
        storyboardWorkflow={storyboardWorkflow}
        shots={shots}
      />
      <footer className={styles.scriptWorkbenchFooter}>
        <button
          type="button"
          className={styles.scriptAddShotButton}
          onClick={(event) => event.stopPropagation()}
        >
          <Plus size={17} />
          {t("aigcStudio.scriptNode.addShot", "添加镜头")}
        </button>
        <button
          type="button"
          className={styles.scriptPrimaryAction}
          onClick={(event) => {
            event.stopPropagation();
            scriptWorkflow.handleScriptWorkflowStepChange(node, "assets");
          }}
        >
          {t("aigcStudio.scriptNode.nextPrepareAssets", "下一步：准备资产")}
        </button>
      </footer>
    </>
  );
}

function ScriptAssetSection({
  title,
  assets,
  t,
  progress,
}: {
  title: string;
  assets: ScriptAssetItem[];
  t: Translate;
  progress: number;
}) {
  const placeholderByKind: Record<ScriptAssetKind, string> = {
    character: t(
      "aigcStudio.scriptNode.assets.characterPlaceholder",
      "生成或上传角色图",
    ),
    scene: t(
      "aigcStudio.scriptNode.assets.scenePlaceholder",
      "生成或上传场景图",
    ),
    prop: t("aigcStudio.scriptNode.assets.propPlaceholder", "生成或上传道具图"),
  };

  return (
    <section className={styles.scriptAssetSection}>
      <h3>{title}</h3>
      <div className={styles.scriptAssetCards}>
        {assets.map((asset) => (
          <article className={styles.scriptAssetCard} key={asset.id}>
            <div className={styles.scriptAssetPreview}>
              {asset.status === "generating" ? (
                <span className={styles.scriptAssetGeneratingBadge}>
                  {t(
                    "aigcStudio.scriptNode.assets.generating",
                    "生成中 {{progress}}%...",
                    { progress },
                  )}
                  <button
                    type="button"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {t("common.cancel", "取消")}
                  </button>
                </span>
              ) : isScriptAssetReady(asset) ? (
                <span className={styles.scriptAssetReadyPreview}>
                  {asset.label.slice(0, 1)}
                </span>
              ) : (
                <span className={styles.scriptAssetPlaceholderText}>
                  {placeholderByKind[asset.kind]}
                </span>
              )}
            </div>
            <strong>{asset.label}</strong>
            <span>{asset.description}</span>
          </article>
        ))}
        <button
          type="button"
          className={styles.scriptAssetAddButton}
          onClick={(event) => event.stopPropagation()}
        >
          <Plus size={20} />
          新增
        </button>
      </div>
    </section>
  );
}

function ScriptAssetGenerateDialog({
  assets,
  node,
  t,
  modelOptions,
  scriptWorkflow,
  onClose,
}: {
  assets: ScriptAssetItem[];
  node: AigcCanvasNode;
  t: Translate;
  modelOptions?: AigcCapabilityInfo[];
  scriptWorkflow: ScriptNodeWorkflow;
  onClose: () => void;
}) {
  const selectedIds = assets.map((asset) => asset.id);
  const assetModelOptions = scriptAssetModelOptionsFrom(modelOptions);
  const initialModelOption =
    assetModelOptions[0] ?? FALLBACK_SCRIPT_ASSET_MODELS[0];
  const initialProfile = imageModelParameterProfileFor(
    initialModelOption.model,
  );
  const [openMenu, setOpenMenu] = useState<ScriptAssetDialogMenu | null>(null);
  const [selectedModelKey, setSelectedModelKey] = useState(
    initialModelOption.key,
  );
  const [imageQuality, setImageQuality] = useState(
    initialProfile.defaultQuality || DEFAULT_IMAGE_QUALITY,
  );
  const [resolution, setResolution] = useState(
    preferredScriptAssetResolution(initialProfile.resolutions),
  );
  const [aspectRatio, setAspectRatio] = useState(
    preferredScriptAssetAspectRatio(initialProfile.aspectRatios),
  );
  const selectedModelOption =
    assetModelOptions.find((option) => option.key === selectedModelKey) ??
    initialModelOption;
  const parameterProfile = imageModelParameterProfileFor(
    selectedModelOption.model,
  );
  const parameterSelection = normalizedImageParameterSelection(
    parameterProfile,
    {
      aspectRatio,
      imageQuality,
      resolution,
    },
  );
  const activeImageQuality = parameterSelection.imageQuality;
  const activeResolution = parameterSelection.resolution;
  const activeAspectRatio = parameterSelection.aspectRatio;
  const ratioOptions = scriptAssetRatioOptions(parameterProfile.aspectRatios);
  const energyCost = selectedIds.length * 18;
  const groups: Array<{
    title: string;
    kind: ScriptAssetKind;
  }> = [
    {
      title: t("aigcStudio.scriptNode.assets.characters", "角色"),
      kind: "character",
    },
    { title: t("aigcStudio.scriptNode.assets.scenes", "场景"), kind: "scene" },
    { title: t("aigcStudio.scriptNode.assets.props", "道具"), kind: "prop" },
  ];
  const toggleMenu = (menu: ScriptAssetDialogMenu) => {
    setOpenMenu((current) => (current === menu ? null : menu));
  };
  const handleSelectModel = (option: ScriptAssetModelOption) => {
    const nextProfile = imageModelParameterProfileFor(option.model);
    setSelectedModelKey(option.key);
    setImageQuality((current) =>
      nextProfile.showQuality && IMAGE_QUALITY_OPTIONS.includes(current)
        ? current
        : nextProfile.defaultQuality || DEFAULT_IMAGE_QUALITY,
    );
    setResolution((current) =>
      nextProfile.resolutions.includes(current)
        ? current
        : preferredScriptAssetResolution(nextProfile.resolutions),
    );
    setAspectRatio((current) =>
      nextProfile.aspectRatios.includes(current)
        ? current
        : preferredScriptAssetAspectRatio(nextProfile.aspectRatios),
    );
    setOpenMenu(null);
  };

  return (
    <div
      className={styles.scriptModalBackdrop}
      onClick={(event) => {
        event.stopPropagation();
        onClose();
      }}
    >
      <section
        role="dialog"
        aria-label={t(
          "aigcStudio.scriptNode.generateAllAssets",
          "一键生成所有资产",
        )}
        className={styles.scriptAssetGenerateDialog}
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.scriptDialogHeader}>
          <h3>
            {t("aigcStudio.scriptNode.generateAllAssets", "一键生成所有资产")}
          </h3>
          <button
            type="button"
            aria-label={t("common.close", "关闭")}
            onClick={onClose}
          >
            <X size={17} />
          </button>
        </header>
        <div className={styles.scriptDialogList}>
          {groups.map((group) => {
            const groupAssets = assets.filter(
              (asset) => asset.kind === group.kind,
            );
            if (!groupAssets.length) return null;
            return (
              <section key={group.kind}>
                <h4>{group.title}</h4>
                {groupAssets.map((asset) => (
                  <label className={styles.scriptDialogRow} key={asset.id}>
                    <input type="checkbox" checked readOnly />
                    <span>
                      <strong>{asset.label}</strong>
                      <em>{asset.description}</em>
                    </span>
                  </label>
                ))}
              </section>
            );
          })}
        </div>
        <footer className={styles.scriptDialogFooter}>
          <label className={styles.scriptDialogSelectAll}>
            <input type="checkbox" checked readOnly />
            {t(
              "aigcStudio.scriptNode.selectedAssets",
              "已选 {{count}}/{{total}}",
              {
                count: selectedIds.length,
                total: assets.length,
              },
            )}
          </label>
          <div className={styles.scriptDialogControls}>
            <div className={styles.scriptDialogControlWrap}>
              <button
                type="button"
                className={styles.scriptDialogControl}
                onClick={() => toggleMenu("model")}
              >
                <Sparkles size={14} />
                <span>{selectedModelOption.label}</span>
                <ChevronDown size={13} />
              </button>
              {openMenu === "model" && (
                <div
                  className={styles.scriptDialogDropdown}
                  data-testid="aigc-script-asset-model-menu"
                >
                  {assetModelOptions.map((option) => (
                    <button
                      type="button"
                      key={option.key}
                      className={
                        option.key === selectedModelOption.key
                          ? styles.scriptDialogOptionActive
                          : ""
                      }
                      onClick={() => handleSelectModel(option)}
                    >
                      <Sparkles size={14} />
                      <span>{option.label}</span>
                      {option.key === selectedModelOption.key && (
                        <Check size={14} />
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {parameterProfile.showQuality && (
              <div className={styles.scriptDialogControlWrap}>
                <button
                  type="button"
                  className={styles.scriptDialogControl}
                  onClick={() => toggleMenu("quality")}
                >
                  <span>{activeImageQuality}</span>
                  <ChevronDown size={13} />
                </button>
                {openMenu === "quality" && (
                  <div
                    className={styles.scriptDialogDropdown}
                    data-testid="aigc-script-asset-quality-menu"
                  >
                    {IMAGE_QUALITY_OPTIONS.map((quality) => (
                      <button
                        type="button"
                        key={quality}
                        className={
                          quality === activeImageQuality
                            ? styles.scriptDialogOptionActive
                            : ""
                        }
                        onClick={() => {
                          setImageQuality(quality);
                          setOpenMenu(null);
                        }}
                      >
                        <span>{quality}</span>
                        {quality === activeImageQuality && <Check size={14} />}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className={styles.scriptDialogControlWrap}>
              <button
                type="button"
                className={styles.scriptDialogControl}
                onClick={() => toggleMenu("resolution")}
              >
                <span>{activeResolution}</span>
                <ChevronDown size={13} />
              </button>
              {openMenu === "resolution" && (
                <div
                  className={styles.scriptDialogDropdown}
                  data-testid="aigc-script-asset-resolution-menu"
                >
                  {parameterProfile.resolutions.map((item) => (
                    <button
                      type="button"
                      key={item}
                      className={
                        item === activeResolution
                          ? styles.scriptDialogOptionActive
                          : ""
                      }
                      onClick={() => {
                        setResolution(item);
                        setOpenMenu(null);
                      }}
                    >
                      <span>{item}</span>
                      {item === activeResolution && <Check size={14} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className={styles.scriptDialogControlWrap}>
              <button
                type="button"
                className={styles.scriptDialogControl}
                onClick={() => toggleMenu("ratio")}
              >
                <span className={styles.scriptDialogRatioIcon} />
                <span>{activeAspectRatio}</span>
                <ChevronDown size={13} />
              </button>
              {openMenu === "ratio" && (
                <div
                  className={styles.scriptDialogDropdown}
                  data-testid="aigc-script-asset-ratio-menu"
                >
                  {ratioOptions.map((ratio) => (
                    <button
                      type="button"
                      key={ratio}
                      className={
                        ratio === activeAspectRatio
                          ? styles.scriptDialogOptionActive
                          : ""
                      }
                      onClick={() => {
                        setAspectRatio(ratio);
                        setOpenMenu(null);
                      }}
                    >
                      <span className={styles.scriptDialogRatioIcon} />
                      <span>{ratio}</span>
                      {ratio === activeAspectRatio && <Check size={14} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <span className={styles.scriptDialogEnergy}>
            <Zap size={14} />
            {energyCost}
          </span>
          <button
            type="button"
            className={styles.scriptPrimaryAction}
            onClick={() => {
              scriptWorkflow.handleScriptAssetsGenerateAll(node, selectedIds, {
                modelLabel: selectedModelOption.label,
                providerId: selectedModelOption.model?.provider_id,
                providerName: selectedModelOption.model?.provider_name,
                modelId: selectedModelOption.model?.model_id,
                modelCapability: selectedModelOption.model?.capability,
                imageQuality: parameterProfile.showQuality
                  ? activeImageQuality
                  : undefined,
                resolution: activeResolution,
                aspectRatio: activeAspectRatio,
              });
              onClose();
            }}
          >
            {t(
              "aigcStudio.scriptNode.generateSelectedAssets",
              "生成({{count}})",
              {
                count: selectedIds.length,
              },
            )}
          </button>
        </footer>
      </section>
    </div>
  );
}

function ScriptParseFailure({
  node,
  t,
  scriptWorkflow,
}: ScriptResultPanelProps) {
  const parseError = panelTextValue(node.data.scriptParseError);
  const rawOutput = panelTextValue(node.data.scriptRawOutput);

  return (
    <>
      <section
        className={styles.scriptParseFailure}
        data-testid="aigc-script-parse-failure"
      >
        <div className={styles.scriptParseFailureCopy}>
          <strong>
            {t("aigcStudio.scriptNode.parseFailureTitle", "脚本解析失败")}
          </strong>
          <p>
            {t(
              "aigcStudio.scriptNode.parseFailureDescription",
              "模型返回内容不是可识别的分镜 JSON，暂时无法进入确认镜头。",
            )}
          </p>
        </div>
        {parseError ? (
          <p className={styles.scriptParseError}>{parseError}</p>
        ) : null}
        {rawOutput ? (
          <pre className={styles.scriptParseRaw}>{rawOutput}</pre>
        ) : null}
      </section>
      <footer className={styles.scriptWorkbenchFooter}>
        <span className={styles.scriptFooterHint}>
          {t(
            "aigcStudio.scriptNode.parseFailureHint",
            "请重新生成脚本，或切换更适合结构化输出的文本模型。",
          )}
        </span>
        <button
          type="button"
          className={styles.scriptPrimaryAction}
          onClick={(event) => {
            event.stopPropagation();
            scriptWorkflow.handleScriptRegenerate(node);
          }}
        >
          {t("aigcStudio.scriptNode.regenerateScript", "重新生成脚本")}
        </button>
      </footer>
    </>
  );
}

function ScriptAssetsStep({
  node,
  t,
  modelOptions,
  scriptWorkflow,
  assets,
}: ScriptResultPanelProps & {
  assets: ScriptAssetItem[];
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const allAssetsReady =
    assets.length > 0 && assets.every((asset) => isScriptAssetReady(asset));
  const isGenerating = assets.some((asset) => asset.status === "generating");
  const progress = Number(node.data.scriptAssetProgress ?? 4);
  const missing = assets.filter((asset) => !isScriptAssetReady(asset)).length;

  return (
    <>
      <div
        className={styles.scriptAssetWorkspace}
        data-testid="aigc-script-assets"
      >
        <div className={styles.scriptAssetBoard}>
          <ScriptAssetSection
            title={t("aigcStudio.scriptNode.assets.characters", "角色")}
            assets={assets.filter((asset) => asset.kind === "character")}
            t={t}
            progress={progress}
          />
          <ScriptAssetSection
            title={t("aigcStudio.scriptNode.assets.scenes", "场景")}
            assets={assets.filter((asset) => asset.kind === "scene")}
            t={t}
            progress={progress}
          />
          <ScriptAssetSection
            title={t("aigcStudio.scriptNode.assets.props", "道具")}
            assets={assets.filter((asset) => asset.kind === "prop")}
            t={t}
            progress={progress}
          />
        </div>
      </div>
      {confirmOpen && (
        <ScriptAssetGenerateDialog
          assets={assets}
          node={node}
          t={t}
          modelOptions={modelOptions}
          scriptWorkflow={scriptWorkflow}
          onClose={() => setConfirmOpen(false)}
        />
      )}
      <footer className={styles.scriptWorkbenchFooter}>
        <div className={styles.scriptWorkbenchFooterGroup}>
          <button
            type="button"
            className={styles.scriptAddShotButton}
            onClick={(event) => {
              event.stopPropagation();
              scriptWorkflow.handleScriptWorkflowStepChange(node, "shots");
            }}
          >
            {t("aigcStudio.scriptNode.backConfirmShots", "返回确认镜头")}
          </button>
          <span className={styles.scriptFooterHint}>
            {allAssetsReady
              ? t(
                  "aigcStudio.scriptNode.assets.readyHint",
                  "资产已生成，如果再次生成将会覆盖之前的图片/场景/道具等资产",
                )
              : t(
                  "aigcStudio.scriptNode.assets.missingHint",
                  "检测到有 {{count}} 个资产未生成，您可以手动上传或批量生成",
                  { count: missing },
                )}
          </span>
        </div>
        {allAssetsReady ? (
          <button
            type="button"
            className={styles.scriptPrimaryAction}
            onClick={(event) => {
              event.stopPropagation();
              scriptWorkflow.handleScriptWorkflowStepChange(node, "prompts");
            }}
          >
            {t(
              "aigcStudio.scriptNode.nextComposePrompts",
              "下一步：合成提示词",
            )}
          </button>
        ) : (
          <button
            type="button"
            className={styles.scriptSecondaryAction}
            disabled={isGenerating}
            onClick={(event) => {
              event.stopPropagation();
              setConfirmOpen(true);
            }}
          >
            {t("aigcStudio.scriptNode.generateAllAssets", "一键生成所有资产")}
          </button>
        )}
      </footer>
    </>
  );
}

function ScriptPromptsStep({
  node,
  t,
  scriptWorkflow,
  storyboardWorkflow,
  shots,
}: ScriptResultPanelProps & {
  shots: ScriptShot[];
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [detailShot, setDetailShot] = useState<ScriptShot | null>(null);
  const states = scriptPromptStatesFromNode(node);
  const isGenerating = shots.some(
    (shot) => scriptPromptStatusForShot(states, shot.id) === "generating",
  );
  const promptProgress = Number(node.data.scriptPromptProgress ?? 3);

  return (
    <>
      <div
        className={styles.scriptPromptTablePanel}
        data-testid="aigc-script-prompts"
      >
        <ScriptShotTable
          node={node}
          selectable={false}
          t={t}
          scriptWorkflow={scriptWorkflow}
          storyboardWorkflow={storyboardWorkflow}
          shots={shots}
          promptStates={states}
          promptProgress={promptProgress}
          onViewPrompt={setDetailShot}
        />
      </div>
      {confirmOpen && (
        <ScriptPromptComposeDialog
          node={node}
          t={t}
          scriptWorkflow={scriptWorkflow}
          shots={shots}
          onClose={() => setConfirmOpen(false)}
        />
      )}
      {detailShot && (
        <ScriptPromptDetailDialog
          node={node}
          t={t}
          scriptWorkflow={scriptWorkflow}
          shot={detailShot}
          onClose={() => setDetailShot(null)}
        />
      )}
      <footer className={styles.scriptWorkbenchFooter}>
        <button
          type="button"
          className={styles.scriptSecondaryAction}
          onClick={(event) => {
            event.stopPropagation();
            scriptWorkflow.handleScriptWorkflowStepChange(node, "assets");
          }}
        >
          {t("aigcStudio.scriptNode.backPrepareAssets", "返回准备资产")}
        </button>
        <button
          type="button"
          className={styles.scriptPrimaryAction}
          disabled={isGenerating}
          onClick={(event) => {
            event.stopPropagation();
            setConfirmOpen(true);
          }}
        >
          {t("aigcStudio.scriptNode.composeAllPrompts", "一键合成全部提示词")}
        </button>
      </footer>
    </>
  );
}

function ScriptPromptComposeDialog({
  node,
  t,
  scriptWorkflow,
  shots,
  onClose,
}: {
  node: AigcCanvasNode;
  t: Translate;
  scriptWorkflow: ScriptNodeWorkflow;
  shots: ScriptShot[];
  onClose: () => void;
}) {
  const selectedShotIds = shots.map((shot) => shot.id);
  return (
    <div
      className={styles.scriptModalBackdrop}
      onClick={(event) => {
        event.stopPropagation();
        onClose();
      }}
    >
      <section
        role="dialog"
        aria-label={t(
          "aigcStudio.scriptNode.prompts.composeDialogTitle",
          "合成最终提示词",
        )}
        className={styles.scriptPromptComposeDialog}
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.scriptDialogHeader}>
          <h3>
            {t(
              "aigcStudio.scriptNode.prompts.composeDialogTitle",
              "合成最终提示词",
            )}
          </h3>
          <button
            type="button"
            aria-label={t("common.close", "关闭")}
            onClick={onClose}
          >
            <X size={17} />
          </button>
        </header>
        <div className={styles.scriptDialogList}>
          {shots.map((shot) => (
            <label className={styles.scriptDialogRow} key={shot.id}>
              <input type="checkbox" checked readOnly />
              <span>
                <strong>
                  {t("aigcStudio.scriptNode.prompts.shotName", "镜头 {{no}}", {
                    no: shot.no,
                  })}
                </strong>
                <em>{shot.imageDescription}</em>
              </span>
              <button type="button">
                {t("aigcStudio.scriptNode.prompts.detail", "详情")}
              </button>
            </label>
          ))}
        </div>
        <footer className={styles.scriptDialogFooter}>
          <span>
            <input type="checkbox" checked readOnly />
            {t("aigcStudio.scriptNode.prompts.selectAll", "全选镜头")}
          </span>
          <span>
            {t(
              "aigcStudio.scriptNode.prompts.selectedCount",
              "已选{{count}}/{{total}}",
              { count: selectedShotIds.length, total: shots.length },
            )}
          </span>
          <span>GVLM 3.1 Flash</span>
          <button
            type="button"
            className={styles.scriptPrimaryAction}
            onClick={() => {
              scriptWorkflow.handleScriptPromptsGenerateAll(
                node,
                selectedShotIds,
              );
              onClose();
            }}
          >
            {t("aigcStudio.scriptNode.prompts.confirmGenerate", "确认生成")}
          </button>
        </footer>
      </section>
    </div>
  );
}

function ScriptPromptDetailDialog({
  node,
  t,
  scriptWorkflow,
  shot,
  onClose,
}: {
  node: AigcCanvasNode;
  t: Translate;
  scriptWorkflow: ScriptNodeWorkflow;
  shot: ScriptShot;
  onClose: () => void;
}) {
  const title = t(
    "aigcStudio.scriptNode.prompts.detailDialogTitle",
    "第 {{no}} 镜：最终提示词",
    { no: shot.no },
  );
  return (
    <div
      className={styles.scriptModalBackdrop}
      onClick={(event) => {
        event.stopPropagation();
        onClose();
      }}
    >
      <section
        role="dialog"
        aria-label={title}
        className={styles.scriptPromptDetailDialog}
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.scriptDialogHeader}>
          <h3>{title}</h3>
          <button
            type="button"
            aria-label={t("common.close", "关闭")}
            onClick={onClose}
          >
            <X size={17} />
          </button>
        </header>
        <div className={styles.scriptPromptDialogBody}>
          <section className={styles.scriptPromptDialogSection}>
            <h4>
              {t("aigcStudio.scriptNode.prompts.imagePrompt", "分镜提示词")}
            </h4>
            <p>{shot.prompt}</p>
          </section>
          <section className={styles.scriptPromptDialogSection}>
            <h4>
              {t(
                "aigcStudio.scriptNode.prompts.motionPrompt",
                "视频运动提示词",
              )}
            </h4>
            <p>{shot.videoPrompt}</p>
          </section>
        </div>
        <footer className={styles.scriptDialogFooter}>
          <span>GVLM 3.1 Flash</span>
          <button
            type="button"
            className={styles.scriptPrimaryAction}
            onClick={(event) => {
              event.stopPropagation();
              scriptWorkflow.handleScriptPromptGenerate(node, shot.id);
            }}
          >
            {t("aigcStudio.scriptNode.prompts.regenerateOne", "重新合成提示词")}
          </button>
        </footer>
      </section>
    </div>
  );
}

export function ScriptResultPanel({
  node,
  t,
  modelOptions,
  scriptWorkflow,
  storyboardWorkflow,
}: ScriptResultPanelProps) {
  const shots = scriptShotsFromNode(node);
  const groups = assetGroupsFromShots(shots);
  const assets = scriptAssetsFromGroups(node, groups);
  const step = scriptWorkflowStep(node);
  const parseFailed = node.data.scriptParseStatus === "failed" && !shots.length;

  return (
    <div
      className={`${styles.scriptResultPanel} ${styles.scriptPanelFullscreen}`}
      data-testid="aigc-script-workbench"
    >
      <ScriptWorkbenchHeader
        node={node}
        t={t}
        scriptWorkflow={scriptWorkflow}
        storyboardWorkflow={storyboardWorkflow}
        shots={shots}
        assets={assets}
      />
      <main className={styles.scriptWorkbenchBody}>
        {parseFailed ? (
          <ScriptParseFailure
            node={node}
            t={t}
            scriptWorkflow={scriptWorkflow}
            storyboardWorkflow={storyboardWorkflow}
          />
        ) : step === "assets" ? (
          <ScriptAssetsStep
          node={node}
          t={t}
          modelOptions={modelOptions}
          scriptWorkflow={scriptWorkflow}
          storyboardWorkflow={storyboardWorkflow}
          assets={assets}
          />
        ) : step === "prompts" ? (
          <ScriptPromptsStep
            node={node}
            t={t}
            scriptWorkflow={scriptWorkflow}
            storyboardWorkflow={storyboardWorkflow}
            shots={shots}
          />
        ) : (
          <ScriptShotsStep
            node={node}
            t={t}
            scriptWorkflow={scriptWorkflow}
            storyboardWorkflow={storyboardWorkflow}
            shots={shots}
          />
        )}
      </main>
    </div>
  );
}
