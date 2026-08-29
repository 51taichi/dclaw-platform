import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  message,
  Modal,
  Space,
  Spin,
  Tabs,
  Tag,
  Upload,
} from "antd";
import { billingApi } from "../../../api/modules/billing";
import type {
  PriceableModel,
  PricingAudit,
  PricingOverview,
  PricingUnlock,
} from "../../../api/types/billing";
import PricingDrafts from "./PricingDrafts";
import PricingHistory from "./PricingHistory";
import PricingModels from "./PricingModels";
import PricingOverviewView from "./PricingOverview";
import PricingRules from "./PricingRules";
import PricingUnlockModal from "./PricingUnlockModal";

export default function PricingTab() {
  const [overview, setOverview] = useState<PricingOverview>();
  const [models, setModels] = useState<PriceableModel[]>([]);
  const [history, setHistory] = useState<PricingAudit[]>([]);
  const [error, setError] = useState<string>();
  const [unlock, setUnlock] = useState<PricingUnlock>();
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
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
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = unlock
    ? Math.max(0, Math.ceil((Date.parse(unlock.expires_at) - now) / 1000))
    : 0;
  const activeUnlock = remaining > 0 ? unlock : undefined;
  const initialize = async () => {
    if (!activeUnlock) {
      setUnlockOpen(true);
      return;
    }
    const preview = await billingApi.initializePricingPreview(
      activeUnlock.token,
    );
    if (!preview.publishable || !preview.catalog_id) {
      Modal.warning({
        title: "价格草稿暂不可发布",
        content: `仍有 ${preview.blockers.length} 项可信成本缺失。`,
      });
      return;
    }
    Modal.confirm({
      title: "发布首份价格目录？",
      content: `版本 ${preview.version}，共 ${preview.rule_count} 条规则。`,
      onOk: async () => {
        await billingApi.publishPricingPreview(
          preview.catalog_id!,
          activeUnlock.token,
        );
        await load();
        message.success("价格目录已发布");
      },
    });
  };
  const importFile = async (file: File) => {
    if (!activeUnlock) {
      setUnlockOpen(true);
      return false;
    }
    const preview = await billingApi.previewPricingImport(file);
    if (preview.status === "blocked")
      Modal.error({
        title: "Excel预检未通过",
        content: `发现 ${preview.rows.length} 项问题。`,
      });
    else
      Modal.confirm({
        title: "确认导入价格草稿？",
        content: `预检通过 ${preview.valid_rows.length} 行，导入后仍需单独发布。`,
        onOk: async () => {
          await billingApi.confirmPricingImport(preview.id, activeUnlock.token);
          await load();
        },
      });
    return false;
  };
  const exportExcel = async () => {
    const blob = await billingApi.exportPricing();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "pricing-rmb.xlsx";
    anchor.click();
    URL.revokeObjectURL(url);
  };
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
      <Space wrap>
        <Button
          type={activeUnlock ? "default" : "primary"}
          onClick={() => setUnlockOpen(true)}
        >
          解锁计费设置
        </Button>
        {activeUnlock && (
          <Tag color="green">
            已解锁 · 剩余 {String(Math.floor(remaining / 60)).padStart(2, "0")}:
            {String(remaining % 60).padStart(2, "0")}
          </Tag>
        )}
        <Button disabled={!activeUnlock} onClick={() => void initialize()}>
          生成初始化草稿
        </Button>
        <Upload
          accept=".xlsx"
          showUploadList={false}
          beforeUpload={(file) => {
            void importFile(file);
            return false;
          }}
        >
          <Button disabled={!activeUnlock}>导入Excel</Button>
        </Upload>
        <Button onClick={() => void exportExcel()}>导出Excel</Button>
      </Space>
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
          {
            key: "rules",
            label: "定价规则",
            children: (
              <PricingRules
                disabled={!activeUnlock}
                onSave={async (value) => {
                  if (!activeUnlock) return;
                  await billingApi.savePricingPolicy(value, activeUnlock.token);
                  await load();
                  message.success("倍数规则已保存");
                }}
              />
            ),
          },
          {
            key: "drafts",
            label: "价格草稿",
            children: (
              <PricingDrafts
                catalogs={overview.catalogs}
                canMutate={Boolean(activeUnlock)}
                onRollback={(id) => {
                  if (!activeUnlock) return;
                  Modal.confirm({
                    title: "确认回滚价格目录？",
                    content: "回滚会生成新的目录版本，仅影响新请求。",
                    onOk: async () => {
                      await billingApi.rollbackPricingCatalog(
                        id,
                        activeUnlock.token,
                      );
                      await load();
                    },
                  });
                }}
              />
            ),
          },
          {
            key: "history",
            label: "历史与审计",
            children: <PricingHistory rows={history} />,
          },
        ]}
      />
      <PricingUnlockModal
        open={unlockOpen}
        onCancel={() => setUnlockOpen(false)}
        onUnlocked={(value) => {
          setUnlock(value);
          setNow(Date.now());
          setUnlockOpen(false);
        }}
      />
    </Space>
  );
}
