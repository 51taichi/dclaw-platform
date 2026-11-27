import { Text, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import AssetImage from "../../components/AssetImage";
import StateView from "../../components/StateView";
import TaskCard from "../../components/TaskCard";
import usePageShare from "../../hooks/usePageShare";
import { requireAuth } from "../../services/auth";
import {
  getWorkbench,
  type MobileTaskSummary,
  type MobileWorkbenchResponse,
} from "../../services/mobile";
import { applyWorkbenchSummary } from "../../stores/mobileStore";

import "./index.scss";

const AIGC_WEB_URL = "https://dclaw.deepmega.cn/";

export default function WorkbenchPage() {
  usePageShare({
    title: "DClaw｜企业 AI 助手",
    path: "/pages/workbench/index",
  });

  const [summary, setSummary] = useState<MobileWorkbenchResponse | null>(null);
  const [knowledgeGuideOpen, setKnowledgeGuideOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const loadWorkbench = async () => {
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
    loadWorkbench();
  });

  const openTask = (task: MobileTaskSummary) => {
    Taro.navigateTo({ url: `/pages/task-detail/index?chatId=${task.id}` });
  };

  const openAigcWebGuide = () => {
    Taro.showModal({
      title: "请到 Web 版体验",
      content: `AIGC 创意项目暂时仅支持 PC Web 版，请在电脑浏览器打开：${AIGC_WEB_URL}`,
      confirmText: "复制链接",
      cancelText: "我知道了",
      success: (result) => {
        if (result.confirm) {
          Taro.setClipboardData({
            data: AIGC_WEB_URL,
          });
        }
      },
    });
  };

  const openKnowledgeGuide = () => {
    setKnowledgeGuideOpen(true);
  };

  const closeKnowledgeGuide = () => {
    setKnowledgeGuideOpen(false);
  };

  const startTaskFromKnowledgeGuide = () => {
    setKnowledgeGuideOpen(false);
    Taro.navigateTo({ url: "/pages/create-task/index" });
  };

  return (
    <AppShell className="workbench-page" tabActive="workbench">
      <Text className="page-title">工作台</Text>
      <View className="card hero-card">
        <View className="hero-copy">
          <Text className="hero-title">Hi，伙伴</Text>
          <Text className="hero-subtitle">今天想让 DClaw 帮你做点什么？</Text>
          <View
            className="hero-button"
            onClick={() => Taro.navigateTo({ url: "/pages/create-task/index" })}
          >
            <Text>发起任务</Text>
            <Text className="hero-button__plus">+</Text>
          </View>
        </View>
        <View className="hero-mascot-frame">
          <AssetImage slot="mascotHero" className="hero-mascot" />
        </View>
      </View>

      <View className="shortcut-grid">
        <View
          className="shortcut shortcut--tasks"
          onClick={() => Taro.redirectTo({ url: "/pages/tasks/index" })}
        >
          <AssetImage slot="shortcutTasks" className="shortcut__icon" />
          <Text className="shortcut__label">我的任务</Text>
        </View>
        <View
          className="shortcut shortcut--knowledge"
          onClick={openKnowledgeGuide}
        >
          <AssetImage slot="shortcutKnowledge" className="shortcut__icon" />
          <Text className="shortcut__label">知识库用法</Text>
        </View>
        <View
          className="shortcut shortcut--ai"
          onClick={() => Taro.redirectTo({ url: "/pages/confirmations/index" })}
        >
          <AssetImage slot="shortcutAi" className="shortcut__icon" />
          <Text className="shortcut__label">AI工具确认</Text>
          {!!summary?.pending_confirmation_count && (
            <Text className="shortcut__badge">
              {summary.pending_confirmation_count}
            </Text>
          )}
        </View>
        <View
          className="shortcut shortcut--confirm"
          onClick={openAigcWebGuide}
        >
          <AssetImage slot="shortcutConfirm" className="shortcut__icon" />
          <Text className="shortcut__label">AIGC创意</Text>
        </View>
      </View>

      <View className="section-header">
        <Text className="section-title">我的任务</Text>
        <Text
          className="section-link"
          onClick={() => Taro.redirectTo({ url: "/pages/tasks/index" })}
        >
          全部
        </Text>
      </View>

      <View className="task-list">
        {loading && !summary && (
          <StateView
            type="loading"
            title="正在同步你的工作台"
            description="DClaw 正在整理最近任务和 AI 工具确认"
          />
        )}
        {!!errorMessage && !summary && (
          <StateView
            type="error"
            title="工作台加载失败"
            description={errorMessage}
            actionText="重新加载"
            onAction={loadWorkbench}
          />
        )}
        {!loading &&
          summary?.recent_tasks.map((task) => (
            <TaskCard key={task.id} task={task} onTap={openTask} />
          ))}
        {!loading && !errorMessage && !summary?.recent_tasks.length && (
          <StateView
            type="empty"
            title="还没有任务"
            description="发起第一个任务后，它会出现在这里"
            actionText="发起任务"
            onAction={() => Taro.navigateTo({ url: "/pages/create-task/index" })}
          />
        )}
      </View>
      {knowledgeGuideOpen && (
        <View className="knowledge-guide">
          <View className="knowledge-guide__mask" onClick={closeKnowledgeGuide} />
          <View className="knowledge-guide__panel">
            <Text className="knowledge-guide__title">知识库怎么用</Text>
            <View className="knowledge-guide__steps">
              <View className="knowledge-guide__step">
                <Text className="knowledge-guide__index">1</Text>
                <View className="knowledge-guide__copy">
                  <Text className="knowledge-guide__step-title">发起任务</Text>
                  <Text className="knowledge-guide__step-desc">
                    从工作台点击“发起任务”。
                  </Text>
                </View>
              </View>
              <View className="knowledge-guide__step">
                <Text className="knowledge-guide__index">2</Text>
                <View className="knowledge-guide__copy">
                  <Text className="knowledge-guide__step-title">
                    任务目标里写明参考范围
                  </Text>
                  <Text className="knowledge-guide__step-desc">
                    可以写“参考企业知识库”或“参考个人知识库”。
                  </Text>
                </View>
              </View>
              <View className="knowledge-guide__step">
                <Text className="knowledge-guide__index">3</Text>
                <View className="knowledge-guide__copy">
                  <Text className="knowledge-guide__step-title">补充材料</Text>
                  <Text className="knowledge-guide__step-desc">
                    可继续添加文件或图片，DClaw 会在任务执行中检索并整理结果。
                  </Text>
                </View>
              </View>
            </View>
            <View className="knowledge-guide__actions">
              <Text
                className="knowledge-guide__button knowledge-guide__button--ghost"
                onClick={closeKnowledgeGuide}
              >
                我知道了
              </Text>
              <Text
                className="knowledge-guide__button knowledge-guide__button--primary"
                onClick={startTaskFromKnowledgeGuide}
              >
                发起任务
              </Text>
            </View>
          </View>
        </View>
      )}
    </AppShell>
  );
}
