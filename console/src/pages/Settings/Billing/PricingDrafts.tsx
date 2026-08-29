import { Button, Table, Tag } from "antd";
import type { PricingCatalogSummary } from "../../../api/types/billing";

export default function PricingDrafts({
  catalogs,
  canMutate = false,
  onRollback,
}: {
  catalogs: PricingCatalogSummary[];
  canMutate?: boolean;
  onRollback?: (id: string) => void;
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
        {
          title: "操作",
          render: (_, row) =>
            row.status === "published" ? (
              <Button
                danger
                disabled={!canMutate}
                onClick={() => onRollback?.(row.id)}
              >
                回滚到此版本
              </Button>
            ) : null,
        },
      ]}
    />
  );
}
