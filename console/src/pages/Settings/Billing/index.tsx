import { Tabs, Typography } from "antd";
import ProductsTab from "./ProductsTab";
import {
  PricingTab,
  ReconciliationTab,
  RolloutTab,
  UsageTab,
} from "./RemoteDataTabs";
import TopUpClaimsTab from "./TopUpClaimsTab";

export default function BillingSettings() {
  return (
    <div>
      <Typography.Title level={2}>积分与计费管理</Typography.Title>
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
  );
}
