import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Modal,
  Radio,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { billingApi } from "../../../api/modules/billing";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import type { BillingUsageOrder } from "../../../api/types/billing";
export { default as PricingTab } from "./PricingTab";
export { default as ReconciliationTab } from "./ReconciliationTab";

const sourceLabels: Record<string, string> = {
  client: "客户端",
  mobile: "移动端",
  openapi: "OpenAPI",
  expert_team: "专家团",
  automation: "自动化",
  schedule: "定时任务",
  channel: "渠道",
};

const statusLabels: Record<string, { label: string; color: string }> = {
  quoted: { label: "已报价", color: "default" },
  held: { label: "已冻结", color: "processing" },
  settled: { label: "已结算", color: "success" },
  reconciling: { label: "对账中", color: "warning" },
};

const formatNumber = (value: number) => value.toLocaleString("zh-CN");

export function UsageTab() {
  const [rows, setRows] = useState<BillingUsageOrder[]>([]);
  const [userNames, setUserNames] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<BillingUsageOrder | null>(null);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void Promise.allSettled([
      billingApi.listAdminUsage(),
      adminUsersApi.listUsers(),
    ]).then(([usageResult, userResult]) => {
      if (usageResult.status === "fulfilled") {
        setRows(usageResult.value.items);
      } else {
        setError(String(usageResult.reason));
      }
      if (userResult.status === "fulfilled") {
        setUserNames(
          Object.fromEntries(
            userResult.value.map((user) => [String(user.id), user.username]),
          ),
        );
      }
      setLoading(false);
    });
  }, []);

  if (error) return <Alert type="error" message={error} />;

  return (
    <>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        scroll={{ x: 1120 }}
        columns={[
          {
            title: "账号",
            width: 150,
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <Typography.Text strong>
                  {row.owner_user_id
                    ? userNames[row.owner_user_id] ?? "未知账号"
                    : "系统"}
                </Typography.Text>
                {row.owner_user_id && (
                  <Typography.Text type="secondary">
                    ID {row.owner_user_id}
                  </Typography.Text>
                )}
              </Space>
            ),
          },
          {
            title: "来源",
            width: 110,
            dataIndex: "source",
            render: (source: string) => sourceLabels[source] ?? source,
          },
          {
            title: "Token 用量",
            width: 160,
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <span>输入 {formatNumber(row.tokens.input)}</span>
                <Typography.Text type="secondary">
                  输出 {formatNumber(row.tokens.output)}
                </Typography.Text>
              </Space>
            ),
          },
          {
            title: "积分",
            width: 150,
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <span>报价 {formatNumber(row.quoted_credits)}</span>
                <Typography.Text type="secondary">
                  实扣 {formatNumber(row.actual_debited_credits)}
                </Typography.Text>
              </Space>
            ),
          },
          { title: "调用次数", width: 100, dataIndex: "call_count" },
          {
            title: "状态",
            width: 100,
            dataIndex: "status",
            render: (status: string) => {
              const option = statusLabels[status];
              return <Tag color={option?.color}>{option?.label ?? status}</Tag>;
            },
          },
          {
            title: "创建时间",
            width: 170,
            dataIndex: "created_at",
            render: (value: string) =>
              dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
          },
          {
            title: "操作",
            width: 100,
            fixed: "right",
            render: (_, row) => (
              <Button type="link" onClick={() => setSelected(row)}>
                查看详情
              </Button>
            ),
          },
        ]}
      />
      <Modal
        title="消费记录详情"
        open={Boolean(selected)}
        footer={null}
        width={720}
        onCancel={() => setSelected(null)}
      >
        {selected && (
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="记录 ID" span={2}>
              {selected.id}
            </Descriptions.Item>
            <Descriptions.Item label="账号">
              {selected.owner_user_id
                ? `${userNames[selected.owner_user_id] ?? "未知账号"}（ID ${
                    selected.owner_user_id
                  }）`
                : "系统"}
            </Descriptions.Item>
            <Descriptions.Item label="来源">
              {sourceLabels[selected.source] ?? selected.source}
            </Descriptions.Item>
            <Descriptions.Item label="计费模式">
              {selected.billing_mode}
            </Descriptions.Item>
            <Descriptions.Item label="目录版本">
              {selected.catalog_version}
            </Descriptions.Item>
            <Descriptions.Item label="报价积分">
              {formatNumber(selected.quoted_credits)}
            </Descriptions.Item>
            <Descriptions.Item label="实际扣减">
              {formatNumber(selected.actual_debited_credits)}
            </Descriptions.Item>
            <Descriptions.Item label="冻结 / 结算 / 释放" span={2}>
              {formatNumber(selected.credits.held)} /{" "}
              {formatNumber(selected.credits.captured)} /{" "}
              {formatNumber(selected.credits.released)}
            </Descriptions.Item>
            <Descriptions.Item label="输入 Token">
              {formatNumber(selected.tokens.input)}
            </Descriptions.Item>
            <Descriptions.Item label="输出 Token">
              {formatNumber(selected.tokens.output)}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {dayjs(selected.created_at).format("YYYY-MM-DD HH:mm:ss")}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {dayjs(selected.updated_at).format("YYYY-MM-DD HH:mm:ss")}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </>
  );
}
export function RolloutTab() {
  const [mode, setMode] = useState<"off" | "shadow" | "observe" | "enforced">(
    "shadow",
  );
  const [current, setCurrent] = useState<Record<string, unknown>>({});
  useEffect(() => {
    void billingApi.getRollout().then(setCurrent);
  }, []);
  return (
    <Card title="计费灰度">
      <p>当前：{String(current.mode ?? "未激活")}</p>
      <Radio.Group
        value={mode}
        onChange={(event) => setMode(event.target.value)}
        options={["off", "shadow", "observe", "enforced"]}
      />
      <Button
        onClick={() => void billingApi.activateRollout(mode).then(setCurrent)}
      >
        确认切换
      </Button>
    </Card>
  );
}
