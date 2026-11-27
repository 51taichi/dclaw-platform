import { Image, View } from "@tarojs/components";

import "./index.scss";

const SLOT_FILES = {
  logo: "dclaw-logo.png",
  mascotHero: "mascot-hero-runtime.png",
  mascotTab: "mascot-tab-runtime.png",
  mascotTask: "mascot-task-runtime.png",
  mascotConfirm: "mascot-confirm-runtime.png",
  mascotEmpty: "mascot-empty-runtime.png",
  mascotResult: "mascot-result-runtime.png",
  mascotLogin: "mascot-login-runtime.png",
  mascotKnowledge: "mascot-knowledge-runtime.png",
  mascotError: "mascot-error-runtime.png",
  shortcutTasks: "icon-shortcut-tasks.png",
  shortcutKnowledge: "icon-shortcut-knowledge.png",
  shortcutAi: "icon-shortcut-ai.png",
  shortcutConfirm: "icon-shortcut-confirm.png",
  taskFile: "icon-task-file.png",
  tabWorkbench: "icon-tab-workbench.png",
  tabTasks: "icon-tab-tasks.png",
  tabConfirm: "icon-tab-confirm.png",
  tabMe: "icon-tab-me.png",
  tabWorkbenchActive: "icon-tab-workbench-active.png",
  tabWorkbenchInactive: "icon-tab-workbench-inactive.png",
  tabTasksActive: "icon-tab-tasks-active.png",
  tabTasksInactive: "icon-tab-tasks-inactive.png",
  tabConfirmActive: "icon-tab-confirm-active.png",
  tabConfirmInactive: "icon-tab-confirm-inactive.png",
  tabMeActive: "icon-tab-me-active.png",
  tabMeInactive: "icon-tab-me-inactive.png",
} as const;

export type AssetSlot = keyof typeof SLOT_FILES;

interface AssetImageProps {
  slot: AssetSlot;
  className?: string;
  mode?: "aspectFit" | "aspectFill" | "widthFix";
}

export default function AssetImage({
  slot,
  className = "",
  mode = "aspectFit",
}: AssetImageProps) {
  const src = `/assets/${SLOT_FILES[slot]}`;
  return (
    <View className={`asset-image ${className}`}>
      <Image className="asset-image__img" mode={mode} src={src} />
    </View>
  );
}
