import { Card, Table } from "@agentscope-ai/design";
import { Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { CreditConsumptionRankingItem } from "../../../../api/types/tokenUsage";
import styles from "../index.module.less";

interface CreditRankingTableProps {
  items: CreditConsumptionRankingItem[];
  loading: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number, pageSize: number) => void;
}

export function CreditRankingTable({
  items,
  loading,
  page,
  pageSize,
  total,
  onPageChange,
}: CreditRankingTableProps) {
  const { t } = useTranslation();
  const columns = [
    {
      title: t("tokenUsage.rank", "排名"),
      dataIndex: "rank",
      key: "rank",
      width: 88,
    },
    {
      title: t("tokenUsage.customerAccount", "客户账号"),
      dataIndex: "username",
      key: "username",
      render: (username: string, row: CreditConsumptionRankingItem) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{username}</Typography.Text>
          <Typography.Text type="secondary">ID {row.user_id}</Typography.Text>
        </Space>
      ),
    },
    {
      title: t("tokenUsage.actualConsumedCredits", "实际消耗积分"),
      dataIndex: "consumed_credits",
      key: "consumed_credits",
      render: (value: number) => value.toLocaleString("zh-CN"),
    },
    {
      title: t("tokenUsage.totalCalls", "调用次数"),
      dataIndex: "call_count",
      key: "call_count",
      render: (value: number) => value.toLocaleString("zh-CN"),
    },
  ];

  return (
    <Card
      className={styles.tableCard}
      title={t("tokenUsage.creditRanking", "客户积分消耗排行")}
    >
      <Table
        rowKey="user_id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          onChange: onPageChange,
        }}
        size="small"
      />
    </Card>
  );
}
