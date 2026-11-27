import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  Bot,
  BriefcaseBusiness,
  Building2,
  ChartNoAxesCombined,
  ContactRound,
  ExternalLink,
  Globe,
  Headset,
  LifeBuoy,
  MessagesSquare,
  ShoppingBag,
} from "lucide-react";

export const DEFAULT_SCENE_ICON = "external-link";

export const SCENE_ICON_OPTIONS = [
  { value: DEFAULT_SCENE_ICON, label: "外链", Icon: ExternalLink },
  { value: "headset", label: "客服", Icon: Headset },
  { value: "bot", label: "机器人", Icon: Bot },
  { value: "globe", label: "官网", Icon: Globe },
  { value: "contact", label: "联系人", Icon: ContactRound },
  { value: "building", label: "企业", Icon: Building2 },
  { value: "shopping-bag", label: "商城", Icon: ShoppingBag },
  { value: "briefcase", label: "工作", Icon: BriefcaseBusiness },
  { value: "book-open", label: "知识库", Icon: BookOpen },
  { value: "chart", label: "数据分析", Icon: ChartNoAxesCombined },
  { value: "messages", label: "消息", Icon: MessagesSquare },
  { value: "life-buoy", label: "帮助", Icon: LifeBuoy },
] as const satisfies ReadonlyArray<{
  value: string;
  label: string;
  Icon: LucideIcon;
}>;

export type SceneIconName = (typeof SCENE_ICON_OPTIONS)[number]["value"];

const SCENE_ICON_MAP = new Map<string, LucideIcon>(
  SCENE_ICON_OPTIONS.map(({ value, Icon }) => [value, Icon]),
);

export function normalizeSceneIcon(value: unknown): SceneIconName {
  const candidate = typeof value === "string" ? value : "";
  return SCENE_ICON_MAP.has(candidate)
    ? (candidate as SceneIconName)
    : DEFAULT_SCENE_ICON;
}

export function getSceneIcon(value: unknown): LucideIcon {
  return SCENE_ICON_MAP.get(normalizeSceneIcon(value)) ?? ExternalLink;
}
