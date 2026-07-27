import { Button, Text, View } from "@tarojs/components";

import AssetImage from "../AssetImage";
import type { AssetSlot } from "../AssetImage";

import "./index.scss";

type StateType = "loading" | "empty" | "error";

interface StateViewProps {
  type: StateType;
  title: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
}

const STATE_ASSETS: Record<StateType, AssetSlot> = {
  loading: "mascotTask",
  empty: "mascotEmpty",
  error: "mascotError",
};

export default function StateView({
  type,
  title,
  description,
  actionText,
  onAction,
}: StateViewProps) {
  return (
    <View className={`state-view state-view--${type}`}>
      <AssetImage slot={STATE_ASSETS[type]} className="state-view__mascot" />
      <Text className="state-view__title">{title}</Text>
      {!!description && (
        <Text className="state-view__description">{description}</Text>
      )}
      {!!actionText && !!onAction && (
        <Button className="state-view__button" onClick={onAction}>
          {actionText}
        </Button>
      )}
    </View>
  );
}
