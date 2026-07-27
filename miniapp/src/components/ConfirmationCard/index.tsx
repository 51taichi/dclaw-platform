import { Button, Text, View } from "@tarojs/components";

import type { MobilePendingConfirmation } from "../../services/mobile";

import "./index.scss";

interface ConfirmationCardProps {
  confirmation: MobilePendingConfirmation;
  onApprove: (requestId: string) => void;
  onDeny: (requestId: string) => void;
}

function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params);
  if (!entries.length) {
    return "无参数";
  }
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

export default function ConfirmationCard({
  confirmation,
  onApprove,
  onDeny,
}: ConfirmationCardProps) {
  const deadline = confirmation.created_at + confirmation.timeout_seconds;
  const remainingSeconds = Math.max(
    0,
    Math.floor(deadline - Date.now() / 1000),
  );

  return (
    <View className="confirmation-card">
      <View className="confirmation-card__header">
        <Text className="confirmation-card__title">
          {confirmation.tool_name}
        </Text>
        <Text className="confirmation-card__risk">
          风险：{confirmation.severity}
        </Text>
      </View>
      <Text className="confirmation-card__summary">
        {confirmation.findings_summary || "需要你确认后继续执行"}
      </Text>
      <Text className="confirmation-card__params">
        {formatParams(confirmation.tool_params)}
      </Text>
      <Text className="confirmation-card__countdown">
        {remainingSeconds > 0
          ? `${remainingSeconds} 秒后超时`
          : "已超时，请刷新状态"}
      </Text>
      <View className="confirmation-card__actions">
        <Button
          className="confirmation-card__button confirmation-card__button--deny"
          onClick={() => onDeny(confirmation.request_id)}
        >
          拒绝
        </Button>
        <Button
          className="confirmation-card__button confirmation-card__button--approve"
          onClick={() => onApprove(confirmation.request_id)}
        >
          确认执行
        </Button>
      </View>
    </View>
  );
}
