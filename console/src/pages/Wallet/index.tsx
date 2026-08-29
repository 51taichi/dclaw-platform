import { useCallback, useEffect, useState } from "react";
import { Alert, Card, Col, Row, Spin, Tabs, Typography } from "antd";
import { billingApi } from "../../api/modules/billing";
import type {
  BillingLedgerEntry,
  BillingUsageOrder,
  BillingWallet,
  TopUpClaim,
  TopUpConfig,
  TopUpProduct,
} from "../../api/types/billing";
import ClaimHistory from "./components/ClaimHistory";
import LedgerTable from "./components/LedgerTable";
import TopUpPanel from "./components/TopUpPanel";
import UsageOrders from "./components/UsageOrders";

export default function WalletPage() {
  const [wallet, setWallet] = useState<BillingWallet | null>(null);
  const [config, setConfig] = useState<TopUpConfig | null>(null);
  const [products, setProducts] = useState<TopUpProduct[]>([]);
  const [claims, setClaims] = useState<TopUpClaim[]>([]);
  const [ledger, setLedger] = useState<BillingLedgerEntry[]>([]);
  const [usage, setUsage] = useState<BillingUsageOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [
        nextWallet,
        nextConfig,
        nextProducts,
        nextClaims,
        nextLedger,
        nextUsage,
      ] = await Promise.all([
        billingApi.getWallet(),
        billingApi.getTopUpConfig(),
        billingApi.listProducts(),
        billingApi.listClaims(),
        billingApi.listLedger({ limit: 50 }),
        billingApi.listUsage({ limit: 50 }),
      ]);
      setWallet(nextWallet);
      setConfig(nextConfig);
      setProducts(nextProducts.items);
      setClaims(nextClaims.items);
      setLedger(nextLedger.items);
      setUsage(nextUsage.items);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "积分数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void load(), [load]);
  if (loading) return <Spin />;
  if (!wallet || !config)
    return <Alert type="error" message={error ?? "积分数据不可用"} />;

  return (
    <div>
      <Typography.Title level={2}>积分钱包</Typography.Title>
      {error && <Alert type="warning" message={error} />}
      <Row gutter={16}>
        <Col span={8}>
          <Card title="可用积分">{wallet.available.toLocaleString()}</Card>
        </Col>
        <Col span={8}>
          <Card title="冻结积分">{wallet.held.toLocaleString()}</Card>
        </Col>
        <Col span={8}>
          <Card title="永久购买积分">{wallet.purchased.toLocaleString()}</Card>
        </Col>
      </Row>
      <TopUpPanel
        config={config}
        products={products}
        onSubmit={async (product, paymentChannel, payerReference, key) => {
          await billingApi.submitClaim(
            {
              product_id: product.public_id,
              payment_channel: paymentChannel,
              payer_reference: payerReference,
              customer_note: null,
            },
            key,
          );
          await load();
          window.dispatchEvent(new CustomEvent("dclaw:billing-settled"));
        }}
      />
      <Tabs
        items={[
          {
            key: "claims",
            label: "充值申请",
            children: <ClaimHistory claims={claims} />,
          },
          {
            key: "ledger",
            label: "积分流水",
            children: <LedgerTable rows={ledger} />,
          },
          {
            key: "usage",
            label: "OpenAPI 消费",
            children: <UsageOrders rows={usage} />,
          },
        ]}
      />
    </div>
  );
}
