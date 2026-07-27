import { Button, Text, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import AssetImage from "../../components/AssetImage";
import StateView from "../../components/StateView";
import usePageShare from "../../hooks/usePageShare";
import {
  clearAuthToken,
  getStoredUsername,
  requireAuth,
} from "../../services/auth";
import {
  getWorkbench,
  type MobileWorkbenchResponse,
} from "../../services/mobile";
import { applyWorkbenchSummary } from "../../stores/mobileStore";

import "./index.scss";

const DCLAW_WEB_URL = "https://dclaw.deepmega.cn/";

export default function MePage() {
  usePageShare({
    title: "DClaw｜企业 AI 助手",
    path: "/pages/me/index",
  });

  const [summary, setSummary] = useState<MobileWorkbenchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const profileName = getStoredUsername() || "DClaw 用户";

  const loadSummary = async () => {
    if (!requireAuth()) {
      return;
    }
    setLoading(true);
    setErrorMessage("");
    try {
      const response = await getWorkbench();
      setSummary(response);
      applyWorkbenchSummary(response);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useDidShow(() => {
    loadSummary();
  });

  const logout = () => {
    clearAuthToken();
    Taro.reLaunch({ url: "/pages/login/index" });
  };

  const openTasks = () => {
    Taro.redirectTo({ url: "/pages/tasks/index" });
  };

  const openConfirmations = () => {
    Taro.redirectTo({ url: "/pages/confirmations/index" });
  };

  const openSupport = () => {
    Taro.showModal({
      title: "帮助与反馈",
      content: `如果小程序功能异常，请联系企业管理员，或在电脑浏览器打开：${DCLAW_WEB_URL}`,
      confirmText: "复制链接",
      cancelText: "我知道了",
      success: (result) => {
        if (result.confirm) {
          Taro.setClipboardData({ data: DCLAW_WEB_URL });
        }
      },
    });
  };

  return (
    <AppShell className="me-page" tabActive="me">
      <Text className="page-title">我的</Text>
      <View className="card profile-card">
        <AssetImage slot="mascotLogin" className="profile-avatar" />
        <View className="profile-copy">
          <Text className="profile-name">{profileName}</Text>
          <Text className="profile-meta">当前账号 · 企业空间</Text>
          <Text className="profile-badge">已登录</Text>
        </View>
      </View>

      <View className="stats-row">
        {loading && !summary && (
          <StateView
            type="loading"
            title="正在同步个人信息"
            description="任务统计会马上更新"
          />
        )}
        {!!errorMessage && !summary && (
          <StateView
            type="error"
            title="个人信息加载失败"
            description={errorMessage}
            actionText="重新加载"
            onAction={loadSummary}
          />
        )}
        {summary && (
          <>
            <View className="card stat-card" onClick={openTasks}>
              <Text className="stat-value">{summary.running_task_count}</Text>
              <Text className="stat-label">处理中</Text>
            </View>
            <View className="card stat-card" onClick={openConfirmations}>
              <Text className="stat-value">
                {summary.pending_confirmation_count}
              </Text>
              <Text className="stat-label">待确认</Text>
            </View>
          </>
        )}
      </View>

      <View className="card entry-list">
        <Text className="entry-title">常用入口</Text>
        <View className="entry-item" onClick={openTasks}>
          <View className="entry-copy">
            <Text className="entry-label">我的任务</Text>
            <Text className="entry-desc">查看处理中和历史任务</Text>
          </View>
          <Text className="entry-arrow">&gt;</Text>
        </View>
        <View className="entry-item" onClick={openConfirmations}>
          <View className="entry-copy">
            <Text className="entry-label">确认记录</Text>
            <Text className="entry-desc">处理 AI 工具执行确认</Text>
          </View>
          <Text className="entry-arrow">&gt;</Text>
        </View>
        <View className="entry-item" onClick={openSupport}>
          <View className="entry-copy">
            <Text className="entry-label">帮助与反馈</Text>
            <Text className="entry-desc">联系管理员或复制 Web 版地址</Text>
          </View>
          <Text className="entry-arrow">&gt;</Text>
        </View>
      </View>

      <Button className="logout-button" onClick={logout}>
        退出登录
      </Button>
    </AppShell>
  );
}
