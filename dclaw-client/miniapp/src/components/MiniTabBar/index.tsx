import { Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";

import AssetImage, { type AssetSlot } from "../AssetImage";
import { getMobileState } from "../../stores/mobileStore";

import "./index.scss";

export type MiniTabKey = "workbench" | "tasks" | "confirmations" | "me";

const TABS: Array<{
  key: MiniTabKey;
  label: string;
  url: string;
}> = [
  {
    key: "workbench",
    label: "工作台",
    url: "/pages/workbench/index",
  },
  {
    key: "tasks",
    label: "任务",
    url: "/pages/tasks/index",
  },
  {
    key: "confirmations",
    label: "确认",
    url: "/pages/confirmations/index",
  },
  {
    key: "me",
    label: "我的",
    url: "/pages/me/index",
  },
];

const TAB_ICON_SLOTS: Record<
  MiniTabKey,
  {
    active: AssetSlot;
    inactive: AssetSlot;
  }
> = {
  workbench: {
    active: "tabWorkbenchActive",
    inactive: "tabWorkbenchInactive",
  },
  tasks: {
    active: "tabTasksActive",
    inactive: "tabTasksInactive",
  },
  confirmations: {
    active: "tabConfirmActive",
    inactive: "tabConfirmInactive",
  },
  me: {
    active: "tabMeActive",
    inactive: "tabMeInactive",
  },
};

function TabIcon({
  active,
  tabKey,
}: {
  active: boolean;
  tabKey: MiniTabKey;
}) {
  const slot = active
    ? TAB_ICON_SLOTS[tabKey].active
    : TAB_ICON_SLOTS[tabKey].inactive;

  return (
    <AssetImage slot={slot} className="mini-tabbar__icon" />
  );
}

export default function MiniTabBar({ active }: { active: MiniTabKey }) {
  const { pendingConfirmationCount } = getMobileState();

  const openTab = (tab: (typeof TABS)[number]) => {
    if (tab.key === active) {
      return;
    }
    Taro.redirectTo({ url: tab.url });
  };

  return (
    <View className="mini-tabbar">
      <View className="mini-tabbar__grid">
        {TABS.slice(0, 2).map((tab) => {
          const isActive = active === tab.key;
          const needsAttention = false;
          return (
            <View
              key={tab.key}
              className={`mini-tabbar__item ${
                isActive ? "mini-tabbar__item--active" : ""
              } ${needsAttention ? "mini-tabbar__item--attention" : ""}`}
              onClick={() => openTab(tab)}
            >
              <TabIcon active={isActive} tabKey={tab.key} />
              <Text className="mini-tabbar__label">{tab.label}</Text>
            </View>
          );
        })}

        <View
          className="mini-tabbar__center-slot"
          onClick={() => Taro.navigateTo({ url: "/pages/create-task/index" })}
        >
          <View className="mini-tabbar__center">
            <AssetImage slot="mascotTab" className="mini-tabbar__mascot" />
          </View>
        </View>

        {TABS.slice(2).map((tab) => {
          const isActive = active === tab.key;
          const needsAttention =
            tab.key === "confirmations" &&
            !isActive &&
            pendingConfirmationCount > 0;
          return (
            <View
              key={tab.key}
              className={`mini-tabbar__item ${
                isActive ? "mini-tabbar__item--active" : ""
              } ${needsAttention ? "mini-tabbar__item--attention" : ""}`}
              onClick={() => openTab(tab)}
            >
              <TabIcon active={isActive} tabKey={tab.key} />
              <Text className="mini-tabbar__label">{tab.label}</Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}
