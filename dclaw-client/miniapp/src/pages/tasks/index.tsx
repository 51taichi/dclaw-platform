import { Input, Text, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useEffect, useRef, useState } from "react";

import AppShell from "../../components/AppShell";
import AssetImage from "../../components/AssetImage";
import StateView from "../../components/StateView";
import TaskCard from "../../components/TaskCard";
import usePageShare from "../../hooks/usePageShare";
import { requireAuth } from "../../services/auth";
import {
  archiveTask,
  deleteTask,
  getTasks,
  type MobileTaskSummary,
} from "../../services/mobile";
import { filterTasksByKeyword } from "./taskSearch";

import "./index.scss";

const TASKS_POLL_INTERVAL_MS = 3000;

function runningTaskIds(tasks: MobileTaskSummary[]) {
  return new Set(
    tasks
      .filter((task) => task.display_status === "running")
      .map((task) => task.id),
  );
}

function hasTaskResult(task: MobileTaskSummary) {
  return (
    task.display_status === "completed" ||
    task.artifact_count > 0 ||
    task.has_assistant_response === true
  );
}

export default function TasksPage() {
  usePageShare({
    title: "DClaw｜我的 AI 任务",
    path: "/pages/tasks/index",
  });

  const [tasks, setTasks] = useState<MobileTaskSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const runningTaskIdsRef = useRef<Set<string>>(new Set());

  const loadTasks = async (options: { silent?: boolean } = {}) => {
    if (!requireAuth()) {
      return;
    }
    if (!options.silent) {
      setLoading(true);
      setErrorMessage("");
    }
    try {
      const nextTasks = await getTasks();
      const hasFinishedTask = nextTasks.some(
        (task) => runningTaskIdsRef.current.has(task.id) && hasTaskResult(task),
      );
      setTasks(nextTasks);
      runningTaskIdsRef.current = runningTaskIds(nextTasks);
      if (options.silent && hasFinishedTask) {
        Taro.showToast({ title: "任务已完成，可查看结果", icon: "none" });
      }
    } catch (error) {
      if (!options.silent) {
        setErrorMessage(error instanceof Error ? error.message : "加载失败");
      }
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  };

  useDidShow(() => {
    void loadTasks();
  });

  const hasRunningTask = tasks.some((task) => task.display_status === "running");
  const visibleTasks = filterTasksByKeyword(tasks, searchQuery);

  useEffect(() => {
    if (!hasRunningTask) {
      return undefined;
    }
    const timer = setInterval(() => {
      void loadTasks({ silent: true });
    }, TASKS_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasRunningTask]);

  const openTask = (task: MobileTaskSummary) => {
    Taro.navigateTo({ url: `/pages/task-detail/index?chatId=${task.id}` });
  };

  const openTaskResult = (task: MobileTaskSummary) => {
    Taro.navigateTo({ url: `/pages/result/index?chatId=${task.id}` });
  };

  const archiveSelectedTask = async (task: MobileTaskSummary) => {
    const result = await Taro.showModal({
      title: "归档任务",
      content: "归档后 Web 端和小程序任务列表都不再显示。",
      confirmText: "归档",
      cancelText: "取消",
    });
    if (!result.confirm) {
      return;
    }
    try {
      await archiveTask(task.id);
      Taro.showToast({ title: "已归档", icon: "success" });
      await loadTasks();
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "归档失败",
        icon: "none",
      });
    }
  };

  const deleteSelectedTask = async (task: MobileTaskSummary) => {
    const result = await Taro.showModal({
      title: "删除任务",
      content: "删除后任务记录会被移除，产物也不会再从任务入口访问。",
      confirmText: "删除",
      cancelText: "取消",
      confirmColor: "#d92d20",
    });
    if (!result.confirm) {
      return;
    }
    try {
      await deleteTask(task.id);
      Taro.showToast({ title: "已删除", icon: "success" });
      await loadTasks();
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "删除失败",
        icon: "none",
      });
    }
  };

  const showTaskActions = async (task: MobileTaskSummary) => {
    const actions = [
      { label: "查看详情", run: () => openTask(task) },
      ...(hasTaskResult(task)
        ? [{ label: "查看结果", run: () => openTaskResult(task) }]
        : []),
      { label: "归档", run: () => archiveSelectedTask(task) },
      { label: "删除", run: () => deleteSelectedTask(task) },
    ];
    try {
      const result = await Taro.showActionSheet({
        itemList: actions.map((action) => action.label),
      });
      const action = actions[result.tapIndex];
      if (action) {
        await action.run();
      }
    } catch {
      // User cancelled the action sheet.
    }
  };

  return (
    <AppShell className="tasks-page" tabActive="tasks">
      <Text className="page-title">任务</Text>
      <View className="tasks-hero">
        <View className="tasks-hero__copy">
          <Text className="tasks-hero__title">你的任务队列</Text>
          <Text className="tasks-hero__desc">处理中、待确认和已完成任务会集中在这里</Text>
        </View>
        <AssetImage slot="mascotTask" className="tasks-hero__mascot" />
      </View>
      <View className="task-search">
        <Text className="task-search__icon">搜</Text>
        <Input
          className="task-search__input"
          value={searchQuery}
          placeholder="搜索任务名称或状态"
          placeholderClass="task-search__placeholder"
          confirmType="search"
          onInput={(event) => {
            setSearchQuery(String(event.detail.value || ""));
          }}
        />
        {!!searchQuery && (
          <Text
            className="task-search__clear"
            onClick={() => setSearchQuery("")}
          >
            清除
          </Text>
        )}
      </View>
      <View className="tasks-list">
        {loading && tasks.length === 0 && (
          <StateView
            type="loading"
            title="正在同步任务"
            description="最近任务会按更新时间显示在这里"
          />
        )}
        {!!errorMessage && tasks.length === 0 && (
          <StateView
            type="error"
            title="任务加载失败"
            description={errorMessage}
            actionText="重新加载"
            onAction={loadTasks}
          />
        )}
        {visibleTasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onTap={openTask}
            onMore={showTaskActions}
          />
        ))}
        {!loading && !errorMessage && tasks.length === 0 && (
          <StateView
            type="empty"
            title="暂无任务"
            description="从工作台发起任务后，可在这里追踪执行进度"
            actionText="发起任务"
            onAction={() => Taro.navigateTo({ url: "/pages/create-task/index" })}
          />
        )}
        {!loading &&
          !errorMessage &&
          tasks.length > 0 &&
          visibleTasks.length === 0 && (
            <StateView
              type="empty"
              title="没有找到相关任务"
              description="换个任务名称或状态试试"
              actionText="清空搜索"
              onAction={() => setSearchQuery("")}
            />
          )}
      </View>
    </AppShell>
  );
}
