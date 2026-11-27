import { Boxes, Image, Map, Package, UserRound } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import type { Translate } from "./types";

type ScriptAssetGroupNodeProps = {
  node: AigcCanvasNode;
  t: Translate;
};

type ScriptAssetKind = "character" | "scene" | "prop";

type ScriptAssetItem = {
  id: string;
  kind: ScriptAssetKind;
  label: string;
  status: string;
  description?: string;
  previewIndex?: number;
};

const ASSET_KIND_LABELS: Record<ScriptAssetKind, string> = {
  character: "角色",
  scene: "场景",
  prop: "道具",
};

const ASSET_KIND_ICONS: Record<ScriptAssetKind, typeof UserRound> = {
  character: UserRound,
  scene: Map,
  prop: Package,
};

function scriptAssetsFromNode(node: AigcCanvasNode): ScriptAssetItem[] {
  const assets = node.data.scriptAssets;
  if (!Array.isArray(assets)) return [];
  return assets.filter((asset): asset is ScriptAssetItem => {
    if (!asset || typeof asset !== "object") return false;
    const record = asset as Record<string, unknown>;
    return (
      typeof record.id === "string" &&
      (record.kind === "character" ||
        record.kind === "scene" ||
        record.kind === "prop") &&
      typeof record.label === "string"
    );
  });
}

function ScriptAssetTile({ asset }: { asset: ScriptAssetItem }) {
  const Icon = ASSET_KIND_ICONS[asset.kind];
  return (
    <div className={styles.scriptAssetGroupTile}>
      <div className={styles.scriptAssetGroupPreview}>
        <Icon size={18} />
        <span>{String(asset.previewIndex ?? "")}</span>
      </div>
      <div>
        <strong>{asset.label}</strong>
        <span>{asset.description}</span>
      </div>
      <em>{asset.status === "ready" ? "已生成" : asset.status}</em>
    </div>
  );
}

export function ScriptAssetGroupNode({ node, t }: ScriptAssetGroupNodeProps) {
  const assets = scriptAssetsFromNode(node);
  const groups: ScriptAssetKind[] = ["character", "scene", "prop"];
  return (
    <>
      <div className={styles.scriptAssetGroupLabel}>
        <span>
          <Boxes size={15} />
          {String(
            node.data.assetName ??
              node.data.title ??
              t("aigcStudio.scriptNode.assetGroupTitle", "脚本资产组"),
          )}
        </span>
        <em>{assets.length}</em>
      </div>
      <div className={styles.scriptAssetGroupNode}>
        <div className={styles.scriptAssetGroupSummary}>
          <Image size={18} />
          <span>
            {String(
              node.data.text ??
                t(
                  "aigcStudio.scriptNode.assetGroupDescription",
                  "角色、场景、道具资产已生成，可用于合成提示词。",
                ),
            )}
          </span>
        </div>
        {groups.map((kind) => {
          const groupedAssets = assets.filter((asset) => asset.kind === kind);
          if (groupedAssets.length === 0) return null;
          return (
            <section key={kind} className={styles.scriptAssetGroupSection}>
              <h3>
                {ASSET_KIND_LABELS[kind]}
                <span>{groupedAssets.length}</span>
              </h3>
              <div className={styles.scriptAssetGroupList}>
                {groupedAssets.map((asset) => (
                  <ScriptAssetTile asset={asset} key={asset.id} />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
