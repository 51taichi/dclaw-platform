import { useEffect, useState } from "react";
import { Button, Input, Modal, Space, Table, Tag, Typography } from "antd";
import { billingApi } from "../../../api/modules/billing";
import type { TopUpClaim } from "../../../api/types/billing";

export default function TopUpClaimsTab() {
  const [claims, setClaims] = useState<TopUpClaim[]>([]);
  const [selected, setSelected] = useState<TopUpClaim | null>(null);
  const [action, setAction] = useState<"approve" | "reject">("approve");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () =>
    setClaims((await billingApi.listAdminClaims()).items);
  useEffect(() => void load(), []);

  const review = async () => {
    if (!selected || !reason.trim()) return;
    setBusy(true);
    try {
      const key = `top-up-review:${
        selected.public_id
      }:${action}:${crypto.randomUUID()}`;
      if (action === "approve") {
        await billingApi.approveClaim(selected.public_id, reason.trim(), key);
      } else {
        await billingApi.rejectClaim(selected.public_id, reason.trim(), key);
      }
      setSelected(null);
      setReason("");
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Table
        rowKey="public_id"
        dataSource={claims}
        columns={[
          { title: "客户", dataIndex: "owner_id" },
          { title: "套餐快照", render: (_, row) => row.product_snapshot.name },
          { title: "付款凭证", dataIndex: "payer_reference" },
          { title: "金额(分)", dataIndex: "payment_amount_fen" },
          { title: "状态", render: (_, row) => <Tag>{row.status}</Tag> },
          {
            title: "操作",
            render: (_, row) =>
              row.status === "pending" ? (
                <Space>
                  <Button
                    aria-label="批准"
                    onClick={() => {
                      setSelected(row);
                      setAction("approve");
                    }}
                  >
                    批准
                  </Button>
                  <Button
                    aria-label="拒绝"
                    danger
                    onClick={() => {
                      setSelected(row);
                      setAction("reject");
                    }}
                  >
                    拒绝
                  </Button>
                </Space>
              ) : null,
          },
        ]}
      />
      <Modal
        open={Boolean(selected)}
        title={action === "approve" ? "确认批准充值" : "确认拒绝充值"}
        okText={action === "approve" ? "确认批准" : "确认拒绝"}
        okButtonProps={{ disabled: !reason.trim() }}
        confirmLoading={busy}
        onOk={() => void review()}
        onCancel={() => setSelected(null)}
      >
        <Typography.Paragraph>
          审核以申请中的不可变套餐快照为准，不能直接修改客户余额。
        </Typography.Paragraph>
        <label htmlFor="top-up-review-reason">审核原因</label>
        <Input.TextArea
          id="top-up-review-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </Modal>
    </>
  );
}
