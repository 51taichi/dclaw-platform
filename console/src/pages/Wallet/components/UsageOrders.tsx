import { Button, Select, Space, Table, Tag } from "antd";
import { useState } from "react";
import { billingApi } from "../../../api/modules/billing";
import type { BillingUsageOrder } from "../../../api/types/billing";

const sourceLabels: Record<BillingUsageOrder["source"], string> = {
  client: "客户端",
  mobile: "移动端",
  openapi: "OpenAPI",
  expert_team: "专家团",
  automation: "自动化",
  schedule: "定时任务",
  channel: "外部渠道",
};

const statusLabels: Record<string, string> = {
  quoted: "待调用",
  held: "已冻结",
  settled: "已结算",
  reconciling: "待对账",
  captured: "已扣费",
  released: "已释放",
};

export default function UsageOrders({
  rows,
  source,
  onSourceChange,
}: {
  rows: BillingUsageOrder[];
  source?: BillingUsageOrder["source"];
  onSourceChange?: (source?: BillingUsageOrder["source"]) => void;
}) {
  const [details, setDetails] = useState<Record<string, BillingUsageOrder>>({});
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Select
        aria-label="消费来源"
        allowClear
        placeholder="全部来源"
        value={source}
        style={{ width: 180 }}
        onChange={onSourceChange}
        options={Object.entries(sourceLabels).map(([value, label]) => ({
          value,
          label,
        }))}
      />
      <Table
        rowKey="id"
        dataSource={rows}
        pagination={false}
        expandable={{
          onExpand: (expanded, row) => {
            if (expanded && !details[row.id]) {
              void billingApi
                .getUsage(row.id)
                .then((detail) =>
                  setDetails((current) => ({ ...current, [row.id]: detail })),
                );
            }
          },
          expandIcon: ({ expanded, onExpand, record }) => (
            <Button
              type="text"
              aria-label={expanded ? "收起调用明细" : "展开调用明细"}
              onClick={(event) => onExpand(record, event)}
            >
              {expanded ? "−" : "+"}
            </Button>
          ),
          expandedRowRender: (row) => {
            const items = details[row.id]?.items ?? row.items ?? [];
            return (
              <Table
                rowKey="call_sequence"
                dataSource={items}
                pagination={false}
                size="small"
                columns={[
                  { title: "序号", dataIndex: "call_sequence" },
                  {
                    title: "专家角色",
                    dataIndex: "expert_role",
                    render: (value) => value || "—",
                  },
                  {
                    title: "模型 / 供应商",
                    render: (_, item) => `${item.model} / ${item.provider}`,
                  },
                  {
                    title: "Token（输入 / 输出）",
                    render: (_, item) =>
                      `${item.tokens.input.toLocaleString()} / ${item.tokens.output.toLocaleString()}`,
                  },
                  { title: "扣除积分", dataIndex: "charged_credits" },
                  {
                    title: "状态",
                    dataIndex: "status",
                    render: (value) => statusLabels[value] ?? value,
                  },
                  { title: "计价版本", dataIndex: "catalog_version" },
                ]}
              />
            );
          },
        }}
        columns={[
          { title: "时间", dataIndex: "created_at" },
          {
            title: "来源",
            dataIndex: "source",
            render: (value) =>
              sourceLabels[value as BillingUsageOrder["source"]],
          },
          {
            title: "专家 / 专家团",
            render: (_, row) => row.expert_team || row.expert || "—",
          },
          { title: "调用次数", dataIndex: "call_count" },
          {
            title: "Token（输入 / 输出）",
            render: (_, row) =>
              `${row.tokens.input.toLocaleString()} / ${row.tokens.output.toLocaleString()}`,
          },
          {
            title: "实际扣分",
            dataIndex: "actual_debited_credits",
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (value) => (
              <Tag color={value === "reconciling" ? "orange" : "green"}>
                {statusLabels[value] ?? value}
              </Tag>
            ),
          },
        ]}
      />
    </Space>
  );
}
