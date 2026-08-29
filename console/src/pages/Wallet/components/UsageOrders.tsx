import { Table } from "antd";
import type { BillingUsageOrder } from "../../../api/types/billing";

export default function UsageOrders({ rows }: { rows: BillingUsageOrder[] }) {
  return (
    <Table
      rowKey="id"
      dataSource={rows}
      pagination={false}
      columns={[
        { title: "时间", dataIndex: "created_at" },
        { title: "模型", dataIndex: "model_key" },
        { title: "能力", dataIndex: "capability" },
        { title: "消耗积分", dataIndex: "captured_credits" },
        { title: "状态", dataIndex: "status" },
      ]}
    />
  );
}
