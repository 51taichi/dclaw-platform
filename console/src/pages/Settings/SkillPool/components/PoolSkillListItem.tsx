import { Button, Checkbox } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
  isSkillHidden,
  isSkillPrivate,
} from "@/utils/skill";
import { getSkillVisual } from "../../../Agent/Skills/components";
import { SkillTagChips } from "./SkillMeta";
import { formatPrivateOwnerLabel } from "../skillPublishScope";
import styles from "../index.module.less";
dayjs.extend(relativeTime);

interface PoolSkillListItemProps {
  skill: PoolSkillSpec;
  isSelected: boolean;
  batchModeEnabled: boolean;
  onToggleSelect: (name: string) => void;
  onEdit: (skill: PoolSkillSpec) => void;
  onBroadcast: (skill: PoolSkillSpec) => void;
  onToggleHidden: (skill: PoolSkillSpec) => void | Promise<void>;
  onDelete: (skill: PoolSkillSpec) => void;
}

export function PoolSkillListItem({
  skill,
  isSelected,
  batchModeEnabled,
  onToggleSelect,
  onEdit,
  onBroadcast,
  onToggleHidden,
  onDelete,
}: PoolSkillListItemProps) {
  const { t } = useTranslation();
  const isBuiltin = isSkillBuiltin(skill.source);
  const isPrivate = isSkillPrivate(skill.visibility);
  const isHidden = isSkillHidden(skill.client_visible);
  const isDefault = skill.config?.is_default === true;
  const privateLabel = formatPrivateOwnerLabel(
    t("skillPool.private", "私有技能"),
    skill.owner_user_id,
  );

  return (
    <div
      className={`${styles.skillListItem} ${
        isSelected ? styles.selectedListItem : ""
      }`}
      onClick={() => {
        if (batchModeEnabled) {
          onToggleSelect(skill.name);
        } else {
          onEdit(skill);
        }
      }}
    >
      {batchModeEnabled && (
        <Checkbox
          checked={isSelected}
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect(skill.name);
          }}
        />
      )}
      <div className={styles.listItemLeft}>
        <span className={styles.fileIcon}>
          {getSkillVisual(skill.name, skill.emoji)}
        </span>
        <div className={styles.listItemInfo}>
          <div className={styles.listItemHeader}>
            <span className={styles.skillTitle}>{skill.name}</span>
            <div className={styles.badgeRow}>
              {isPrivate && (
                <span className={styles.privateTypeBadge}>{privateLabel}</span>
              )}
              {!isPrivate && isBuiltin && (
                <span className={styles.typeBadge}>
                  {t("skillPool.builtin")}
                </span>
              )}
              {!isPrivate && !isBuiltin && (
                <span className={styles.typeBadge}>
                  {t("skillPool.public", "公共")}
                </span>
              )}
              {isDefault && (
                <span className={`${styles.typeBadge} ${styles.defaultTag}`}>
                  🌟 {t("skillPool.default", "默认")}
                </span>
              )}
              {isHidden && (
                <span className={styles.privateTypeBadge}>
                  {t("skillPool.hidden", "已隐藏")}
                </span>
              )}
            </div>
            <span
              className={`${styles.statusValue} ${
                styles[getPoolBuiltinStatusTone(skill.sync_status)]
              }`}
            >
              {getPoolBuiltinStatusLabel(skill.sync_status, t)}
            </span>
            {skill.last_updated && (
              <span className={styles.listItemTime}>
                {t("skills.lastUpdated")} {dayjs(skill.last_updated).fromNow()}
              </span>
            )}
          </div>
          <p className={styles.listItemDesc}>{skill.description || "-"}</p>
          <SkillTagChips tags={skill.tags} />
        </div>
      </div>
      <div className={styles.listItemRight}>
        <Button
          className={styles.actionButton}
          disabled={batchModeEnabled}
          onClick={(e) => {
            e.stopPropagation();
            onBroadcast(skill);
          }}
        >
          {t("skillPool.broadcast")}
        </Button>
        <Button
          className={styles.actionButton}
          disabled={batchModeEnabled}
          onClick={(e) => {
            e.stopPropagation();
            void onToggleHidden(skill);
          }}
        >
          {isHidden ? t("skillPool.show") : t("skillPool.hide")}
        </Button>
        <Button
          danger
          className={styles.deleteButton}
          disabled={batchModeEnabled}
          onClick={(e) => {
            e.stopPropagation();
            void onDelete(skill);
          }}
        >
          {t("skillPool.delete")}
        </Button>
      </div>
    </div>
  );
}
