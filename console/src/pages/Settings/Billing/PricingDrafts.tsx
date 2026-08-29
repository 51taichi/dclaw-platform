import { Table, Tag } from "antd";
import type { PricingCatalogSummary } from "../../../api/types/billing";

export default function PricingDrafts({
  catalogs,
}: {
  catalogs: PricingCatalogSummary[];
}) {
  return (
    <Table
      rowKey="id"
      dataSource={catalogs}
      pagination={false}
      columns={[
        { title: "版本", dataIndex: "version" },
        {
          title: "状态",
          dataIndex: "status",
          render: (value) => (
            <Tag color={value === "published" ? "green" : "blue"}>
              {value === "published" ? "已发布" : "草稿"}
            </Tag>
          ),
        },
        { title: "生效时间", dataIndex: "effective_at" },
      ]}
    />
  );
}
