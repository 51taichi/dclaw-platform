import { useEffect, useState } from "react";
import { Button, Input, Modal, Space, Table, Tag, Typography } from "antd";
import { billingApi } from "../../../api/modules/billing";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import type { TopUpClaim } from "../../../api/types/billing";

const paymentChannelLabels: Record<TopUpClaim["payment_channel"], string> = {
  wechat: "微信",
  alipay: "支付宝",
  bank: "银行转账",
  other: "其他",
};

export default function TopUpClaimsTab() {
  const [claims, setClaims] = useState<TopUpClaim[]>([]);
  const [userNames, setUserNames] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<TopUpClaim | null>(null);
  const [action, setAction] = useState<"approve" | "reject">("approve");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => {
    const [claimResult, userResult] = await Promise.allSettled([
      billingApi.listAdminClaims(),
      adminUsersApi.listUsers(),
    ]);
    if (claimResult.status === "fulfilled") {
      setClaims(claimResult.value.items);
    }
    if (userResult.status === "fulfilled") {
      setUserNames(
        Object.fromEntries(
          userResult.value.map((user) => [String(user.id), user.username]),
        ),
      );
    }
  };
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
          {
            title: "客户",
            dataIndex: "owner_id",
            render: (ownerId: string) => (
              <Space direction="vertical" size={0}>
                <Typography.Text strong>
                  {userNames[ownerId] ?? "未知账号"}
                </Typography.Text>
                <Typography.Text type="secondary">ID {ownerId}</Typography.Text>
              </Space>
            ),
          },
          { title: "套餐快照", render: (_, row) => row.product_snapshot.name },
          { title: "付款凭证", dataIndex: "payer_reference" },
          {
            title: "付款渠道",
            dataIndex: "payment_channel",
            render: (channel: TopUpClaim["payment_channel"]) => (
              <Tag>{paymentChannelLabels[channel]}</Tag>
            ),
          },
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
