import { useRef, useState } from "react";
import {
  Button,
  Card,
  Form,
  Image,
  Input,
  Modal,
  Radio,
  Space,
  Typography,
} from "antd";
import type { TopUpConfig, TopUpProduct } from "../../../api/types/billing";

interface Props {
  config: TopUpConfig;
  products: TopUpProduct[];
  onSubmit: (
    product: TopUpProduct,
    paymentChannel: "wechat" | "alipay" | "bank" | "other",
    payerReference: string,
    idempotencyKey: string,
  ) => Promise<void>;
}

export default function TopUpPanel({ config, products, onSubmit }: Props) {
  const [selected, setSelected] = useState<TopUpProduct | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [channel, setChannel] = useState<"wechat" | "alipay">("wechat");
  const [reference, setReference] = useState("");
  const key = useRef(crypto.randomUUID());

  const submit = async () => {
    if (!selected || !reference.trim()) return;
    setSubmitting(true);
    try {
      await onSubmit(selected, channel, reference.trim(), key.current);
      setSelected(null);
      setReference("");
      key.current = crypto.randomUUID();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card title="购买积分">
      {config.enabled && config.qr_url ? (
        <Space align="start" wrap>
          <Image width={180} src={config.qr_url} alt="固定收款二维码" />
          <Typography.Paragraph>{config.instructions}</Typography.Paragraph>
        </Space>
      ) : (
        <Typography.Text type="secondary">
          人工充值暂未开放，请联系平台管理员。
        </Typography.Text>
      )}
      <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
        {products.map((product) => (
          <Card key={product.public_id} size="small">
            <Space direction="vertical">
              <Typography.Title level={5}>{product.name}</Typography.Title>
              <Typography.Text>
                {product.purchased_credits.toLocaleString()} 永久积分
              </Typography.Text>
              {product.promotional_credits > 0 && (
                <Typography.Text type="success">
                  另赠 {product.promotional_credits.toLocaleString()}{" "}
                  积分，有效期
                  {product.promotional_expiry_days} 天
                </Typography.Text>
              )}
              <Typography.Text strong>
                ¥{(product.payment_amount_fen / 100).toFixed(2)}
              </Typography.Text>
              <Button
                disabled={!config.enabled}
                onClick={() => setSelected(product)}
                aria-label={`选择 ${product.name}`}
              >
                选择
              </Button>
            </Space>
          </Card>
        ))}
      </div>
      <Modal
        open={Boolean(selected)}
        title="确认人工充值申请"
        onCancel={() => setSelected(null)}
        onOk={() => void submit()}
        okText="提交充值申请"
        confirmLoading={submitting}
      >
        <Typography.Paragraph>
          提交后由管理员核对收款记录。积分以平台保存的套餐快照为准。
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="付款方式">
            <Radio.Group
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
            >
              <Radio value="wechat">微信</Radio>
              <Radio value="alipay">支付宝</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            label="付款尾号或凭证号"
            htmlFor="top-up-reference"
            required
          >
            <Input
              id="top-up-reference"
              value={reference}
              onChange={(event) => setReference(event.target.value)}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
