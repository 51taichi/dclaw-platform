import { useEffect, useState } from "react";
import { Alert, Table, Tag } from "antd";
import { billingApi } from "../../../api/modules/billing";
import type { TopUpProduct } from "../../../api/types/billing";

export default function ProductsTab() {
  const [products, setProducts] = useState<TopUpProduct[]>([]);
  useEffect(() => {
    void billingApi.listAdminProducts().then((page) => setProducts(page.items));
  }, []);
  return (
    <>
      <Alert
        type="info"
        message="固定收款二维码由 DCLAW_TOP_UP_QR_URL 和 DCLAW_TOP_UP_INSTRUCTIONS 维护。套餐变更不会改变历史申请快照。"
      />
      <Table
        rowKey="public_id"
        dataSource={products}
        columns={[
          { title: "套餐", dataIndex: "name" },
          { title: "金额(分)", dataIndex: "payment_amount_fen" },
          { title: "永久积分", dataIndex: "purchased_credits" },
          { title: "赠送积分", dataIndex: "promotional_credits" },
          { title: "赠送有效期(天)", dataIndex: "promotional_expiry_days" },
          { title: "状态", render: (_, row) => <Tag>{row.status}</Tag> },
        ]}
      />
    </>
  );
}
