import { Table, Tag } from "antd";
import type { TopUpClaim } from "../../../api/types/billing";

export default function ClaimHistory({ claims }: { claims: TopUpClaim[] }) {
  return (
    <Table
      rowKey="public_id"
      dataSource={claims}
      pagination={false}
      locale={{ emptyText: "暂无充值申请" }}
      columns={[
        { title: "套餐", render: (_, row) => row.product_snapshot.name },
        { title: "付款凭证", dataIndex: "payer_reference" },
        { title: "状态", render: (_, row) => <Tag>{row.status}</Tag> },
        { title: "审核说明", dataIndex: "review_reason" },
      ]}
    />
  );
}
