import { useCallback, useEffect, useState } from "react";
import { Alert, Card, Col, Row, Spin, Tabs } from "antd";
import { WalletCards } from "lucide-react";
import { billingApi } from "../../api/modules/billing";
import type {
  BillingLedgerEntry,
  BillingUsageOrder,
  BillingUsageSummary,
  BillingWallet,
  TopUpClaim,
  TopUpConfig,
  TopUpProduct,
} from "../../api/types/billing";
import ClaimHistory from "./components/ClaimHistory";
import LedgerTable from "./components/LedgerTable";
import TopUpPanel from "./components/TopUpPanel";
import UsageOrders from "./components/UsageOrders";
import ecoStyles from "../shared/ecoPage.module.less";
import styles from "./index.module.less";

export default function WalletPage() {
  const [wallet, setWallet] = useState<BillingWallet | null>(null);
  const [config, setConfig] = useState<TopUpConfig | null>(null);
  const [products, setProducts] = useState<TopUpProduct[]>([]);
  const [claims, setClaims] = useState<TopUpClaim[]>([]);
  const [ledger, setLedger] = useState<BillingLedgerEntry[]>([]);
  const [usage, setUsage] = useState<BillingUsageOrder[]>([]);
  const [usageSummary, setUsageSummary] = useState<BillingUsageSummary | null>(
    null,
  );
  const [usageSource, setUsageSource] = useState<BillingUsageOrder["source"]>();
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
        nextUsageSummary,
      ] = await Promise.all([
        billingApi.getWallet(),
        billingApi.getTopUpConfig(),
        billingApi.listProducts(),
        billingApi.listClaims(),
        billingApi.listLedger({ limit: 50 }),
        billingApi.listUsage({ limit: 50, source: usageSource }),
        billingApi.getSummary(),
      ]);
      setWallet(nextWallet);
      setConfig(nextConfig);
      setProducts(nextProducts.items);
      setClaims(nextClaims.items);
      setLedger(nextLedger.items);
      setUsage(nextUsage.items);
      setUsageSummary(nextUsageSummary);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "积分数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [usageSource]);

  useEffect(() => void load(), [load]);
  if (loading) return <Spin />;
  if (!wallet || !config)
    return <Alert type="error" message={error ?? "积分数据不可用"} />;

  return (
    <div className={`${ecoStyles.ecoPage} ${styles.walletPage}`}>
      <div className={ecoStyles.pageHeader}>
        <div className={ecoStyles.pageTitle}>
          <span className={ecoStyles.pageTitleIcon}>
            <WalletCards size={18} />
          </span>
          积分钱包
        </div>
        <div className={ecoStyles.pageSubtitle}>
          查看积分余额、购买积分并跟踪充值记录。
        </div>
      </div>
      {error && <Alert type="warning" message={error} />}
      <Row gutter={[16, 16]} className={styles.summaryRow}>
        <Col xs={24} sm={8}>
          <Card className={styles.summaryCard}>
            <div className={styles.summaryLabel}>可用积分</div>
            <div className={styles.summaryValue}>
              {wallet.available.toLocaleString()}
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card className={styles.summaryCard}>
            <div className={styles.summaryLabel}>冻结积分</div>
            <div className={styles.summaryValue}>
              {wallet.held.toLocaleString()}
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card className={styles.summaryCard}>
            <div className={styles.summaryLabel}>永久购买积分</div>
            <div className={styles.summaryValue}>
              {wallet.purchased.toLocaleString()}
            </div>
          </Card>
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
        className={styles.historyTabs}
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
            label: "模型消费",
            children: (
              <div>
                {usageSummary && (
                  <Alert
                    type="info"
                    showIcon
                    message={`近 30 天：${usageSummary.totals.model_calls.toLocaleString()} 次模型调用，实际扣除 ${usageSummary.totals.actual_debited_credits.toLocaleString()} 积分，待对账 ${usageSummary.totals.reconciling_credits.toLocaleString()} 积分`}
                  />
                )}
                <UsageOrders
                  rows={usage}
                  source={usageSource}
                  onSourceChange={setUsageSource}
                />
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
