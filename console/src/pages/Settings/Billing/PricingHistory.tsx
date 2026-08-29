import { Table } from "antd";
import type { PricingAudit } from "../../../api/types/billing";

export default function PricingHistory({ rows }: { rows: PricingAudit[] }) {
  return (
    <Table
      rowKey="id"
      dataSource={rows}
      pagination={false}
      columns={[
        { title: "时间", dataIndex: "created_at" },
        { title: "操作", dataIndex: "action" },
        { title: "操作者", dataIndex: "actor_id" },
      ]}
    />
  );
}
