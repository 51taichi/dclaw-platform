import type { PropsWithChildren } from "react";
import { View } from "@tarojs/components";

import MiniTabBar, { type MiniTabKey } from "../MiniTabBar";
import PrivacyAuthorization from "../PrivacyAuthorization";

import "./index.scss";

interface AppShellProps extends PropsWithChildren {
  className?: string;
  tabActive?: MiniTabKey;
}

export default function AppShell({
  children,
  className = "",
  tabActive,
}: AppShellProps) {
  return (
    <View
      className={`app-shell ${
        tabActive ? "app-shell--with-tabbar" : ""
      } ${className}`}
    >
      {children}
      {tabActive && <MiniTabBar active={tabActive} />}
      <PrivacyAuthorization />
    </View>
  );
}
