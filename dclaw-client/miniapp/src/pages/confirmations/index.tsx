import { Text, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import ConfirmationCard from "../../components/ConfirmationCard";
import AssetImage from "../../components/AssetImage";
import StateView from "../../components/StateView";
import usePageShare from "../../hooks/usePageShare";
import { requireAuth } from "../../services/auth";
import {
  approveConfirmation,
  denyConfirmation,
  getConfirmations,
  type MobilePendingConfirmation,
} from "../../services/mobile";
import { setPendingConfirmationCount } from "../../stores/mobileStore";

import "./index.scss";

export default function ConfirmationsPage() {
  usePageShare({
    title: "DClaw｜AI 工具确认",
    path: "/pages/confirmations/index",
  });

  const [confirmations, setConfirmations] = useState<
    MobilePendingConfirmation[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const loadConfirmations = async () => {
    if (!requireAuth()) {
      return;
    }
    setLoading(true);
    setErrorMessage("");
    try {
      const response = await getConfirmations();
      setConfirmations(response);
      setPendingConfirmationCount(response.length);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useDidShow(() => {
    loadConfirmations();
  });

  const handleApprove = async (requestId: string) => {
    try {
      await approveConfirmation(requestId);
      setConfirmations((items) => {
        const nextItems = items.filter((item) => item.request_id !== requestId);
        setPendingConfirmationCount(nextItems.length);
        return nextItems;
      });
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "确认失败",
        icon: "none",
      });
    }
  };

  const handleDeny = async (requestId: string) => {
    try {
      await denyConfirmation(requestId);
      setConfirmations((items) => {
        const nextItems = items.filter((item) => item.request_id !== requestId);
        setPendingConfirmationCount(nextItems.length);
        return nextItems;
      });
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "拒绝失败",
        icon: "none",
      });
    }
  };

  return (
    <AppShell className="confirmations-page" tabActive="confirmations">
      <Text className="page-title">AI工具确认</Text>
      <View className="confirm-hero">
        <View className="confirm-hero__copy">
          <Text className="confirm-hero__title">AI 工具确认</Text>
          <Text className="confirm-hero__desc">敏感工具执行前，会先等你确认</Text>
        </View>
        <AssetImage slot="mascotConfirm" className="confirm-hero__mascot" />
      </View>
      <View className="confirmation-list">
        {loading && confirmations.length === 0 && (
          <StateView
            type="loading"
            title="正在读取待确认操作"
            description="需要你本人确认的 AI 操作会显示在这里"
          />
        )}
        {!!errorMessage && confirmations.length === 0 && (
          <StateView
            type="error"
            title="待确认操作加载失败"
            description={errorMessage}
            actionText="重新加载"
            onAction={loadConfirmations}
          />
        )}
        {!loading &&
          confirmations.map((confirmation) => (
            <ConfirmationCard
              key={confirmation.request_id}
              confirmation={confirmation}
              onApprove={handleApprove}
              onDeny={handleDeny}
            />
          ))}
        {!loading && !errorMessage && confirmations.length === 0 && (
          <StateView
            type="empty"
            title="暂无待确认操作"
            description="当 DClaw 准备执行敏感工具时，会先等你确认"
          />
        )}
      </View>
    </AppShell>
  );
}
