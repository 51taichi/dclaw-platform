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
  PricingPolicy,
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
  const [policies, setPolicies] = useState<PricingPolicy[]>([]);
  const [activeTab, setActiveTab] = useState("overview");
  const [error, setError] = useState<string>();
  const [unlock, setUnlock] = useState<PricingUnlock>();
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  const load = () =>
    Promise.all([
      billingApi.getPricingOverview(),
      billingApi.listPricingModels(),
      billingApi.listPricingHistory(),
      billingApi.listPricingPolicies(),
    ])
      .then(([nextOverview, nextModels, nextHistory, nextPolicies]) => {
        setOverview(nextOverview);
        setModels(nextModels);
        setHistory(nextHistory);
        setPolicies(nextPolicies);
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
    else {
      const included = preview.valid_rows.filter(
        (row) => row.excluded !== true,
      );
      const excluded = preview.valid_rows.filter(
        (row) => row.excluded === true,
      );
      const models = new Set(
        included.map(
          (row) => `${String(row.provider_id)}/${String(row.model_key)}`,
        ),
      );
      const review = preview.pricing_preview?.review;
      Modal.confirm({
        title: "审批并导入价格草稿？",
        width: 900,
        okText: "确认审批导入",
        content: (
          <Space direction="vertical" style={{ width: "100%" }}>
            <div>
              服务端权威预检：
              {review?.included_dimensions ?? included.length}
              个纳入维度、{review?.included_models ?? models.size}
              个纳入模型、{review?.excluded_models ?? excluded.length}
              个排除模型、{review?.manual_dimensions ?? 0} 个人工价格维度。
            </div>
            <div>确认后价格证据即完成审批，仍需单独发布才会正式计费。</div>
            <pre
              style={{
                maxHeight: 320,
                overflow: "auto",
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(review?.rows ?? preview.valid_rows, null, 2)}
            </pre>
          </Space>
        ),
        onOk: async () => {
          const result = (await billingApi.confirmPricingImport(
            preview.id,
            activeUnlock.token,
          )) as { already_confirmed?: boolean };
          await load();
          setActiveTab("drafts");
          if (result.already_confirmed) {
            message.info("该文件此前已审批导入，本次未重复创建价格草稿");
          } else {
            message.success("价格草稿已审批导入");
          }
        },
      });
    }
    return false;
  };
  const exportExcel = async () => {
    const blob = await billingApi.exportPricing();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "pricing-list.xlsx";
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
      {!overview.catalogs.some((item) => item.status === "published") && (
        <Alert
          type="warning"
          showIcon
          message="尚未发布价格目录"
          description={
            "先导出价格清单，在 Excel 中补齐或调整当前启用模型的价格，再导入审核并发布。发布完成前系统不会启用新价格。"
          }
        />
      )}
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
        <Button onClick={() => void exportExcel()}>导出价格清单</Button>
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
      </Space>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
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
                policies={policies}
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
            label: `价格草稿 (${
              overview.catalogs.filter((catalog) => catalog.status === "draft")
                .length
            })`,
            children: (
              <PricingDrafts
                catalogs={overview.catalogs}
                canMutate={Boolean(activeUnlock)}
                onPublish={(id) => {
                  if (!activeUnlock) return;
                  const selected = overview.catalogs.find(
                    (catalog) => catalog.id === id,
                  );
                  const exclusions = Array.isArray(
                    selected?.metadata.exclusions,
                  )
                    ? selected.metadata.exclusions.length
                    : 0;
                  Modal.confirm({
                    title: "确认发布价格目录？",
                    content: `将发布版本 ${selected?.version ?? id}：${
                      selected?.rules?.length ?? 0
                    } 条分层计价规则，${exclusions} 个明确排除模型。发布后只影响新请求，历史价格快照保持不变。`,
                    onOk: async () => {
                      await billingApi.publishPricingPreview(
                        id,
                        activeUnlock.token,
                      );
                      await load();
                      message.success("价格目录已发布");
                    },
                  });
                }}
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
