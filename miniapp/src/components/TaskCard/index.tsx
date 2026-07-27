import { Text, View } from "@tarojs/components";

import type { MobileTaskSummary } from "../../services/mobile";
import AssetImage from "../AssetImage";
import { taskCardMeta } from "./taskCardModel";

import "./index.scss";

interface TaskCardProps {
  task: MobileTaskSummary;
  onTap: (task: MobileTaskSummary) => void;
  onMore?: (task: MobileTaskSummary) => void;
}

const STATUS_LABELS: Record<MobileTaskSummary["display_status"], string> = {
  running: "执行中",
  pending_confirmation: "待确认",
  completed: "已完成",
  failed: "失败",
  idle: "未开始",
};

export default function TaskCard({ task, onTap, onMore }: TaskCardProps) {
  const meta = taskCardMeta(task);

  return (
    <View
      className={`task-card task-card--${task.display_status}`}
      onClick={() => onTap(task)}
    >
      <AssetImage slot="taskFile" className="task-card__icon" />
      <View className="task-card__body">
        <Text className="task-card__title">{task.name}</Text>
        <Text className="task-card__meta">{meta}</Text>
      </View>
      {task.display_status === "running" ? (
        <View className="task-card__running-indicator">
          <View className="task-card__running-dot" />
          <Text className="task-card__running-text">执行中</Text>
        </View>
      ) : (
        <Text className="task-card__status">
          {STATUS_LABELS[task.display_status]}
        </Text>
      )}
      {onMore && (
        <Text
          className="task-card__more"
          onClick={(event) => {
            event.stopPropagation();
            onMore(task);
          }}
        >
          ...
        </Text>
      )}
      <AssetImage slot="mascotTask" className="task-card__avatar" />
    </View>
  );
}
