import {
  Camera,
  CheckCircle2,
  Download,
  Grid2X2,
  Image,
  Maximize2,
  Play,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Square,
} from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import {
  scriptSelectedStoryboardVideoShotIds,
  scriptShotsFromNode,
  scriptStoryboardImageShotIds,
  storyboardImageMode,
} from "../ScriptNode/scriptNodeState";
import type { StoryboardWorkflow, Translate } from "../ScriptNode/types";
import { StoryboardStill } from "./StoryboardStill";

type StoryboardImageNodeProps = {
  node: AigcCanvasNode;
  selected?: boolean;
  t: Translate;
  storyboardWorkflow: StoryboardWorkflow;
};

function StoryboardGroupToolbar({
  node,
  selected,
  t,
  storyboardWorkflow,
}: StoryboardImageNodeProps) {
  const mode = storyboardImageMode(node);
  const count = scriptStoryboardImageShotIds(node).length;

  if (!selected && mode !== "generating") return null;

  return (
    <div
      className={styles.storyboardGroupToolbar}
      onClick={(event) => event.stopPropagation()}
    >
      <span className={styles.storyboardGroupStatusDot} aria-hidden />
      <button type="button" aria-label="图片组">
        <Grid2X2 size={16} />
      </button>
      {mode === "generating" ? (
        <button type="button" className={styles.storyboardGroupStop}>
          <Square size={15} />
          {t(
            "aigcStudio.scriptNode.stopStoryboardGroup",
            "停止 (0/{{count}})",
            {
              count,
            },
          )}
        </button>
      ) : (
        <button
          type="button"
          className={styles.storyboardGroupRun}
          onClick={() => storyboardWorkflow.handleRunStoryboardImageGroup(node)}
        >
          <Play size={15} />
          {t("aigcStudio.scriptNode.runStoryboardGroup", "整组执行")}
        </button>
      )}
      <button type="button">
        <Grid2X2 size={15} />
        {t("aigcStudio.scriptNode.ungroup", "解组")}
      </button>
      <button type="button">
        <Download size={15} />
        {t("aigcStudio.scriptNode.batchDownload", "批量下载")}
      </button>
    </div>
  );
}

function StoryboardImageGenerating({ node, t }: StoryboardImageNodeProps) {
  const selectedIds = new Set(scriptStoryboardImageShotIds(node));
  const shots = scriptShotsFromNode(node).filter((shot) =>
    selectedIds.has(shot.id),
  );
  const progress = Number(node.data.storyboardImageProgress ?? 6);
  return (
    <div
      className={styles.storyboardGeneratorGroup}
      data-testid="aigc-storyboard-image-generating"
    >
      {shots.map((shot) => (
        <div key={shot.id} className={styles.storyboardGeneratorCard}>
          <span className={styles.storyboardProgressBadge}>
            {t(
              "aigcStudio.scriptNode.generatingPercent",
              "生成中 {{progress}}%...",
              { progress },
            )}
            <button type="button">{t("common.cancel", "取消")}</button>
          </span>
        </div>
      ))}
    </div>
  );
}

function StoryboardGrid({
  node,
  t,
  storyboardWorkflow,
}: StoryboardImageNodeProps) {
  const imageIds = new Set(scriptStoryboardImageShotIds(node));
  const selectedVideoIds = new Set(scriptSelectedStoryboardVideoShotIds(node));
  const shots = scriptShotsFromNode(node).filter((shot) =>
    imageIds.has(shot.id),
  );
  const selectedShot =
    shots.find((shot) => shot.id === node.data.selectedStoryboardShotId) ??
    shots[0];
  return (
    <div
      className={styles.storyboardGridWrap}
      data-testid="aigc-storyboard-grid"
    >
      <div className={styles.storyboardGridHeader}>
        <strong>
          {t("aigcStudio.scriptNode.storyboardTitle", "分镜图 - 脚本生成器")}
        </strong>
        <span>
          {t("aigcStudio.scriptNode.completedCount", "已完成 {{count}} 张", {
            count: shots.length,
          })}
        </span>
      </div>
      <div className={styles.storyboardGrid}>
        {shots.map((shot) => (
          <div
            role="button"
            tabIndex={0}
            key={shot.id}
            data-shot-card="true"
            data-testid="aigc-storyboard-shot-card"
            className={`${styles.storyboardShotCard} ${
              styles.storyboardImageCard
            } ${
              selectedShot?.id === shot.id ? styles.storyboardShotActive : ""
            }`}
            onClick={(event) => {
              event.stopPropagation();
              storyboardWorkflow.handleSelectStoryboardShot(node, shot);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              event.stopPropagation();
              storyboardWorkflow.handleSelectStoryboardShot(node, shot);
            }}
          >
            <StoryboardStill shot={shot} />
            <label
              className={styles.storyboardShotSelector}
              onClick={(event) => event.stopPropagation()}
            >
              <input
                type="checkbox"
                aria-label={t(
                  "aigcStudio.scriptNode.selectStoryboardImage",
                  "选择分镜图 {{no}}",
                  { no: shot.no },
                )}
                checked={selectedVideoIds.has(shot.id)}
                onChange={(event) =>
                  storyboardWorkflow.handleToggleStoryboardVideoShot(
                    node,
                    shot.id,
                    event.target.checked,
                  )
                }
              />
              <CheckCircle2 size={14} />
            </label>
            <em>{shot.no}</em>
          </div>
        ))}
      </div>
      {selectedShot && (
        <div
          className={styles.shotImageEditor}
          data-testid="aigc-shot-image-editor"
          onClick={(event) => event.stopPropagation()}
        >
          <div className={styles.shotEditorTools}>
            <button type="button">
              <Sparkles size={14} />
              {t("aigcStudio.scriptNode.style", "风格")}
            </button>
            <button type="button">
              <SlidersHorizontal size={14} />
              {t("aigcStudio.scriptNode.mark", "标记")}
            </button>
            <button type="button">
              <Plus size={14} />
              {t("aigcStudio.scriptNode.reference", "参考")}
            </button>
            <button
              type="button"
              aria-label={t("aigcStudio.scriptNode.expand", "放大节点")}
              className={styles.shotEditorExpand}
            >
              <Maximize2 size={14} />
            </button>
          </div>
          <p>{selectedShot.prompt}</p>
          <div className={styles.shotEditorBar}>
            <span>Lib Image</span>
            <span>自适应</span>
            <span>标准画质</span>
            <span>2K</span>
            <span>
              <Camera size={14} />
              {t("aigcStudio.scriptNode.camera", "摄像机")}
            </span>
            <span>{selectedShot.shotType}</span>
            <button type="button" className={styles.runCircle}>
              <Play size={15} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function StoryboardImageSelect({ node, t }: StoryboardImageNodeProps) {
  const selectedIds = new Set(scriptStoryboardImageShotIds(node));
  const shots = scriptShotsFromNode(node).filter((shot) =>
    selectedIds.has(shot.id),
  );

  return (
    <div className={styles.storyboardGeneratorGroup}>
      {shots.map((shot) => (
        <div key={shot.id} className={styles.storyboardGeneratorCard}>
          <Image size={38} />
          <span>
            {t(
              "aigcStudio.scriptNode.storyboardImagePlaceholder",
              "配置参数生成分镜图",
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

export function StoryboardImageNode({
  node,
  selected = false,
  t,
  storyboardWorkflow,
}: StoryboardImageNodeProps) {
  const mode = storyboardImageMode(node);
  return (
    <>
      <div className={styles.imageNodeLabel}>
        <span>
          <Image size={15} />
          {String(
            node.data.title ??
              t("aigcStudio.scriptNode.storyboardImageNode", "分镜图"),
          )}
        </span>
      </div>
      <StoryboardGroupToolbar
        node={node}
        selected={selected}
        t={t}
        storyboardWorkflow={storyboardWorkflow}
      />
      <div
        className={`${styles.storyboardImageNodePanel} ${
          mode !== "grid" ? styles.storyboardImageNodePanelCompact : ""
        }`}
        data-testid="aigc-storyboard-image-node"
      >
        {mode === "generating" ? (
          <StoryboardImageGenerating
            node={node}
            selected={selected}
            t={t}
            storyboardWorkflow={storyboardWorkflow}
          />
        ) : mode === "grid" ? (
          <StoryboardGrid
            node={node}
            selected={selected}
            t={t}
            storyboardWorkflow={storyboardWorkflow}
          />
        ) : (
          <StoryboardImageSelect
            node={node}
            selected={selected}
            t={t}
            storyboardWorkflow={storyboardWorkflow}
          />
        )}
      </div>
    </>
  );
}
