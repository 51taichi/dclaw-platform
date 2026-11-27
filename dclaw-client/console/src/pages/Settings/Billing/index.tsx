import { Tabs } from "antd";
import { PageHeader } from "../../../components/PageHeader";
import ProductsTab from "./ProductsTab";
import {
  PricingTab,
  ReconciliationTab,
  RolloutTab,
  UsageTab,
} from "./RemoteDataTabs";
import TopUpClaimsTab from "./TopUpClaimsTab";
import styles from "./index.module.less";

export default function BillingSettings() {
  return (
    <div>
      <PageHeader parent="设置" current="积分与计费" />
      <div className={styles.content}>
        <Tabs
          items={[
            { key: "claims", label: "充值审核", children: <TopUpClaimsTab /> },
            { key: "products", label: "充值套餐", children: <ProductsTab /> },
            { key: "pricing", label: "平台定价", children: <PricingTab /> },
            { key: "usage", label: "消费明细", children: <UsageTab /> },
            {
              key: "reconciliation",
              label: "对账",
              children: <ReconciliationTab />,
            },
            { key: "rollout", label: "灰度开关", children: <RolloutTab /> },
          ]}
        />
      </div>
    </div>
  );
}
