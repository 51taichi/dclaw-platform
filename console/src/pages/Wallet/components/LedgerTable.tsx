import { Table } from "antd";
import type { BillingLedgerEntry } from "../../../api/types/billing";

export default function LedgerTable({ rows }: { rows: BillingLedgerEntry[] }) {
  return (
    <Table
      rowKey="id"
      dataSource={rows}
      pagination={false}
      columns={[
        { title: "时间", dataIndex: "created_at" },
        { title: "类型", dataIndex: "event_type" },
        { title: "积分变化", dataIndex: "credit_delta" },
        { title: "状态", dataIndex: "status" },
      ]}
    />
  );
}
