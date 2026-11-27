import { ScrollView, Text, View } from "@tarojs/components";

import "./index.scss";

export interface OptionPickerItem {
  id: string;
  name: string;
  description?: string;
  badge?: string;
}

interface OptionPickerProps {
  open: boolean;
  title: string;
  options: OptionPickerItem[];
  selectedId: string;
  emptyText?: string;
  onClose: () => void;
  onSelect: (id: string) => void;
}

export default function OptionPicker({
  open,
  title,
  options,
  selectedId,
  emptyText = "暂无可选项",
  onClose,
  onSelect,
}: OptionPickerProps) {
  if (!open) {
    return null;
  }
  const listHeight =
    options.length > 6 ? "52vh" : `${Math.max(options.length, 1) * 74}px`;

  return (
    <View className="option-picker">
      <View className="option-picker__mask" onClick={onClose} />
      <View className="option-picker__sheet">
        <View className="option-picker__header">
          <Text className="option-picker__title">{title}</Text>
          <Text className="option-picker__close" onClick={onClose}>
            关闭
          </Text>
        </View>
        {options.length ? (
          <ScrollView
            className="option-picker__list"
            scrollY
            style={{ height: listHeight }}
          >
            {options.map((item) => (
              <View
                key={item.id}
                className={`option-picker__item ${
                  item.id === selectedId ? "option-picker__item--active" : ""
                }`}
                onClick={() => onSelect(item.id)}
              >
                <View className="option-picker__item-copy">
                  <View className="option-picker__item-title-row">
                    <Text className="option-picker__item-name">{item.name}</Text>
                    {!!item.badge && (
                      <Text className="option-picker__badge">{item.badge}</Text>
                    )}
                  </View>
                  {!!item.description && (
                    <Text className="option-picker__item-desc">
                      {item.description}
                    </Text>
                  )}
                </View>
                {item.id === selectedId && (
                  <Text className="option-picker__check">已选</Text>
                )}
              </View>
            ))}
          </ScrollView>
        ) : (
          <Text className="option-picker__empty">{emptyText}</Text>
        )}
      </View>
    </View>
  );
}
