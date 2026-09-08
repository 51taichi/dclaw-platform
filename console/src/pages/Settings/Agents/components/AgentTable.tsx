import { Table, Button, Space, Popconfirm, Select, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import {
  DeleteOutlined,
  EditOutlined,
  LockOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { EyeOff, Eye } from "lucide-react";
import type { AgentSummary } from "../../../../api/types/agents";
import { useTheme } from "../../../../contexts/ThemeContext";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { SortableAgentRow, DragHandle } from "./SortableAgentRow";
import { providerIcon } from "../../Models/components/providerIcon";
import styles from "../index.module.less";

interface AgentTableProps {
  agents: AgentSummary[];
  loading: boolean;
  reordering: boolean;
  onEdit: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onToggle: (agentId: string, currentEnabled: boolean) => void;
  onReorder: (activeId: string, overId: string) => void;
  modelOptions: Array<{ label: string; value: string }>;
  savingModelAgentId: string | null;
  onModelChange: (
    agentId: string,
    model: { provider_id: string; model: string } | null,
  ) => void;
}

export function AgentTable({
  agents,
  loading,
  reordering,
  onEdit,
  onDelete,
  onToggle,
  onReorder,
  modelOptions,
  savingModelAgentId,
  onModelChange,
}: AgentTableProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 6,
      },
    }),
  );

  const disabledStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.35)", opacity: 1 }
    : {};

  const iconStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.85)" }
    : {};

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }

    onReorder(String(active.id), String(over.id));
  };

  const columns: ColumnsType<AgentSummary> = [
    {
      title: "",
      key: "sort",
      width: 56,
      align: "center",
      render: () => (
        <Tooltip title={t("agent.dragHandleTooltip")}>
          <span>
            <DragHandle disabled={reordering || loading} />
          </span>
        </Tooltip>
      ),
    },
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      width: 300,
      render: (_text: string, record: AgentSummary) => (
        <Space>
          <RobotOutlined
            style={{
              fontSize: 16,
              opacity: record.enabled ? 1 : 0.5,
            }}
          />
          <span style={{ opacity: record.enabled ? 1 : 0.5 }}>
            {getAgentDisplayName(record, t)}
          </span>
          {record.agent_type === "sealed" && (
            <Tag color="blue">{t("agent.sealed")}</Tag>
          )}
          {record.open_api_enabled && (
            <Tooltip title="已开放 OpenAPI 接口">
              <Tag color="purple">API</Tag>
            </Tooltip>
          )}
          {!record.enabled && <Tag color="error">{t("agent.disabled")}</Tag>}
        </Space>
      ),
    },
    {
      title: t("agent.id"),
      dataIndex: "id",
      key: "id",
    },
    {
      title: t("agent.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("agent.workspace"),
      dataIndex: "workspace_dir",
      key: "workspace_dir",
      ellipsis: true,
      render: (
        workspaceDir: string | null | undefined,
        record: AgentSummary,
      ) =>
        record.agent_type === "sealed" ? (
          <span style={{ opacity: 0.65 }}>{t("agent.sealedWorkspace")}</span>
        ) : (
          workspaceDir
        ),
    },
    {
      title: t("agent.modelColumn"),
      key: "active_model",
      width: 260,
      render: (_: unknown, record: AgentSummary) => {
        const value = record.active_model
          ? `${record.active_model.provider_id}\u0000${record.active_model.model}`
          : undefined;
        return (
          <Select
            value={value}
            options={modelOptions}
            placeholder={t("agent.modelPlaceholder")}
            allowClear
            showSearch
            optionFilterProp="label"
            loading={savingModelAgentId === record.id}
            disabled={savingModelAgentId !== null}
            style={{ width: "100%" }}
            onChange={(nextValue?: string) => {
              if (!nextValue) {
                onModelChange(record.id, null);
                return;
              }
              const [provider_id, model] = nextValue.split("\u0000", 2);
              if (provider_id && model) {
                onModelChange(record.id, { provider_id, model });
              }
            }}
            labelRender={({ value: selectedValue, label }) => {
              const [providerId] = String(selectedValue).split("\u0000", 1);
              return (
                <Space size={6}>
                  <img
                    src={providerIcon(providerId)}
                    alt=""
                    style={{ width: 16, height: 16 }}
                  />
                  <span>{label ?? record.active_model?.model}</span>
                </Space>
              );
            }}
          />
        );
      },
    },
    {
      title: t("common.actions"),
      key: "actions",
      render: (_: unknown, record: AgentSummary) => {
        if (record.agent_type === "sealed") {
          return (
            <Tooltip title={t("agent.sealedManageHint")}>
              <Space size={6} style={{ opacity: 0.65 }}>
                <LockOutlined />
                <span>{t("agent.sealedManageHint")}</span>
              </Space>
            </Tooltip>
          );
        }

        return (
          <Space>
            <Button
              type="text"
              size="middle"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
              disabled={record.id === "default"}
              style={record.id === "default" ? disabledStyle : iconStyle}
              title={
                record.id === "default"
                  ? t("agent.defaultNotEditable")
                  : undefined
              }
            />
            <Popconfirm
              title={
                record.enabled
                  ? t("agent.disableConfirm")
                  : t("agent.enableConfirm")
              }
              description={
                record.enabled
                  ? t("agent.disableConfirmDesc")
                  : t("agent.enableConfirmDesc")
              }
              onConfirm={() => onToggle(record.id, record.enabled)}
              disabled={record.id === "default"}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="text"
                size="middle"
                icon={record.enabled ? <EyeOff size={14} /> : <Eye size={14} />}
                disabled={record.id === "default"}
                style={record.id === "default" ? disabledStyle : iconStyle}
                title={
                  record.id === "default"
                    ? t("agent.defaultNotDisablable")
                    : undefined
                }
              />
            </Popconfirm>
            <Popconfirm
              title={t("agent.deleteConfirm")}
              description={t("agent.deleteConfirmDesc")}
              onConfirm={() => onDelete(record.id)}
              disabled={record.id === "default"}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="link"
                size="middle"
                danger
                icon={<DeleteOutlined />}
                disabled={record.id === "default"}
                style={record.id === "default" ? disabledStyle : undefined}
                title={
                  record.id === "default"
                    ? t("agent.defaultNotDeletable")
                    : undefined
                }
              />
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <div className={styles.tableCard}>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={(agents || []).map((agent) => agent.id)}
          strategy={verticalListSortingStrategy}
        >
          <Table
            dataSource={agents || []}
            columns={columns}
            loading={loading}
            rowKey="id"
            components={{
              body: {
                row: SortableAgentRow,
              },
            }}
            pagination={false}
          />
        </SortableContext>
      </DndContext>
    </div>
  );
}
