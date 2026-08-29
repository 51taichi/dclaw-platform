import { useEffect, useState } from "react";
import { Alert, Button, Space, Spin, Tabs } from "antd";
import { billingApi } from "../../../api/modules/billing";
import type {
  PriceableModel,
  PricingAudit,
  PricingOverview,
} from "../../../api/types/billing";
import PricingDrafts from "./PricingDrafts";
import PricingHistory from "./PricingHistory";
import PricingModels from "./PricingModels";
import PricingOverviewView from "./PricingOverview";
import PricingRules from "./PricingRules";

export default function PricingTab() {
  const [overview, setOverview] = useState<PricingOverview>();
  const [models, setModels] = useState<PriceableModel[]>([]);
  const [history, setHistory] = useState<PricingAudit[]>([]);
  const [error, setError] = useState<string>();
  const load = () =>
    Promise.all([
      billingApi.getPricingOverview(),
      billingApi.listPricingModels(),
      billingApi.listPricingHistory(),
    ])
      .then(([nextOverview, nextModels, nextHistory]) => {
        setOverview(nextOverview);
        setModels(nextModels);
        setHistory(nextHistory);
        setError(undefined);
      })
      .catch((reason) => setError(String(reason)));
  useEffect(() => {
    void load();
  }, []);
  if (error)
    return (
      <Alert
        type="error"
        message="定价数据加载失败"
        description={error}
        action={<Button onClick={() => void load()}>重试</Button>}
      />
    );
  if (!overview) return <Spin />;
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Tabs
        items={[
          {
            key: "overview",
            label: "定价总览",
            children: <PricingOverviewView value={overview} />,
          },
          {
            key: "models",
            label: "模型价格",
            children: (
              <PricingModels models={models} catalogs={overview.catalogs} />
            ),
          },
          { key: "rules", label: "定价规则", children: <PricingRules /> },
          {
            key: "drafts",
            label: "价格草稿",
            children: <PricingDrafts catalogs={overview.catalogs} />,
          },
          {
            key: "history",
            label: "历史与审计",
            children: <PricingHistory rows={history} />,
          },
        ]}
      />
    </Space>
  );
}
