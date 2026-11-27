import { useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Typography,
} from "antd";
import type { TopUpConfig, TopUpProduct } from "../../../api/types/billing";
import styles from "../index.module.less";

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
  const [customAmount, setCustomAmount] = useState<number | null>(null);
  const key = useRef(crypto.randomUUID());

  const referenceProduct = [...products].sort(
    (left, right) => left.display_order - right.display_order,
  )[0];
  const creditsPerYuan = referenceProduct
    ? referenceProduct.purchased_credits /
      (referenceProduct.payment_amount_fen / 100)
    : 0;
  const estimatedCredits = Math.floor((customAmount ?? 0) * creditsPerYuan);

  const unavailableReason = !config.enabled
    ? "平台尚未开启人工充值，请联系平台管理员。"
    : !config.qr_url
    ? "平台尚未配置收款二维码，请联系平台管理员。"
    : null;

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
    <section className={styles.topUpSection}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>购买积分</div>
        <div className={styles.sectionSubtitle}>
          选择适合的积分套餐，付款并提交凭证后由管理员核对入账。
        </div>
      </div>
      {unavailableReason && (
        <Alert
          className={styles.topUpNotice}
          type="info"
          showIcon
          message={unavailableReason}
        />
      )}
      <div className={styles.productGrid}>
        {products.map((product) => (
          <Card
            key={product.public_id}
            size="small"
            className={styles.productCard}
          >
            <div className={styles.productCardContent}>
              <Typography.Title level={5} className={styles.productTitle}>
                {product.name}
              </Typography.Title>
              <Typography.Text>
                {product.purchased_credits.toLocaleString()} 永久积分
              </Typography.Text>
              <Typography.Text
                className={styles.promotionRow}
                data-testid={`promotion-${product.public_id}`}
                type={product.promotional_credits > 0 ? "success" : undefined}
                aria-hidden={product.promotional_credits <= 0}
              >
                {product.promotional_credits > 0
                  ? `另赠 ${product.promotional_credits.toLocaleString()} 积分，有效期${
                      product.promotional_expiry_days
                    } 天`
                  : null}
              </Typography.Text>
              <Typography.Text strong>
                ¥{(product.payment_amount_fen / 100).toFixed(2)}
              </Typography.Text>
              <Button
                block
                disabled={Boolean(unavailableReason)}
                onClick={() => setSelected(product)}
                aria-label={`选择 ${product.name}`}
              >
                选择
              </Button>
            </div>
          </Card>
        ))}
        <Card
          size="small"
          className={`${styles.productCard} ${styles.customCard}`}
        >
          <div className={styles.productCardContent}>
            <Typography.Title level={5} className={styles.productTitle}>
              自定义金额
            </Typography.Title>
            <InputNumber
              aria-label="自定义充值金额"
              min={1}
              precision={2}
              value={customAmount}
              onChange={setCustomAmount}
              prefix="¥"
              placeholder="请输入充值金额"
              className={styles.customAmountInput}
            />
            <Typography.Text>
              {estimatedCredits > 0
                ? `预计获得 ${estimatedCredits.toLocaleString()} 永久积分`
                : "输入金额后查看预计积分"}
            </Typography.Text>
            <Typography.Text type="secondary" className={styles.customHint}>
              按当前基础兑换比例预估，实际规则以后端为准
            </Typography.Text>
            <Button block disabled aria-label="自定义充值暂需后端支持">
              暂需后端支持
            </Button>
          </div>
        </Card>
      </div>
      <Modal
        open={Boolean(selected)}
        title="确认人工充值申请"
        width={560}
        onCancel={() => setSelected(null)}
        onOk={() => void submit()}
        okText="提交充值申请"
        confirmLoading={submitting}
      >
        {selected && (
          <div className={styles.modalProductSummary}>
            <div>
              <span>套餐</span>
              <strong>{selected.name}</strong>
            </div>
            <div>
              <span>付款金额</span>
              <strong>¥{(selected.payment_amount_fen / 100).toFixed(2)}</strong>
            </div>
            <div>
              <span>永久积分</span>
              <strong>
                {selected.purchased_credits.toLocaleString()} 永久积分
              </strong>
            </div>
          </div>
        )}
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
    </section>
  );
}
