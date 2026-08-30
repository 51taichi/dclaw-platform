import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  message,
  Modal,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Upload,
} from "antd";
import { billingApi } from "../../../api/modules/billing";
import type {
  PriceableModel,
  PricingAudit,
  PricingCollectionJob,
  PricingDraft,
  PricingModelMapping,
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
  const [draft, setDraft] = useState<PricingDraft>();
  const [collectionJob, setCollectionJob] = useState<PricingCollectionJob>();
  const [activeTab, setActiveTab] = useState("overview");
  const [mappings, setMappings] = useState<PricingModelMapping[]>([]);
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
      billingApi.listPricingModelMappings(),
      billingApi.listPricingCollectionJobs(),
    ])
      .then(
        ([
          nextOverview,
          nextModels,
          nextHistory,
          nextPolicies,
          nextMappings,
          nextCollectionJobs,
        ]) => {
          setOverview(nextOverview);
          setModels(nextModels);
          setHistory(nextHistory);
          setPolicies(nextPolicies);
          setMappings(nextMappings);
          setCollectionJob(nextCollectionJobs[0]);
          setError(undefined);
        },
      )
      .catch((reason) => setError(String(reason)));
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (
      !collectionJob ||
      !["pending", "running"].includes(collectionJob.status)
    )
      return;
    const timer = window.setInterval(() => {
      void billingApi
        .getPricingCollectionJob(collectionJob.id)
        .then(setCollectionJob);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [collectionJob?.id, collectionJob?.status]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = unlock
    ? Math.max(0, Math.ceil((Date.parse(unlock.expires_at) - now) / 1000))
    : 0;
  const activeUnlock = remaining > 0 ? unlock : undefined;
  const initialize = async () => {
    const generated = await billingApi.generatePricingDraft();
    setDraft(generated);
    setActiveTab("drafts");
    message.success("已按当前启用平台与模型生成价格草案");
  };
  const collectOfficialPricing = async () => {
    const job = await billingApi.startPricingCollection();
    setCollectionJob(job);
    setActiveTab("drafts");
    message.success("官网价格同步任务已提交，可离开页面后稍后查看");
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
          await billingApi.confirmPricingImport(preview.id, activeUnlock.token);
          await load();
        },
      });
    }
    return false;
  };
  const exportExcel = async () => {
    const blob = draft
      ? await billingApi.exportPricingDraft(draft.draft_key)
      : await billingApi.exportPricing();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = draft ? "pricing-draft.xlsx" : "pricing-rmb.xlsx";
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
            "先生成当前启用模型的价格草案。系统默认按官方成本的 1.5 倍计算，1 元人民币 = 100 积分；缺少可信价格的模型必须补价或填写原因后排除。"
          }
        />
      )}
      {draft && (
        <Alert
          type={draft.coverage.blocking_models ? "warning" : "success"}
          showIcon
          message={`草案覆盖：启用 ${draft.coverage.enabled_models}，已匹配 ${draft.coverage.matched_models}，缺价 ${draft.coverage.missing_models}，已排除 ${draft.coverage.excluded_models}`}
          description={
            draft.coverage.blocking_models
              ? `仍有 ${draft.coverage.blocking_models} 个模型阻塞发布。`
              : "草案覆盖检查已通过，可下载调整后导入审批。"
          }
        />
      )}
      {draft?.coverage.missing_models ? (
        <Alert
          type="info"
          showIcon
          message="缺价模型可精确映射或人工补齐"
          description="优先在价格草稿中配置官方平台与模型的精确映射；若供应商没有可核验的内置价，可在 Excel 缺价行中按填写说明新增多个人工计价维度并提供 HTTPS 价格来源，再导入审批。"
        />
      ) : null}
      {collectionJob && (
        <Alert
          type={collectionJob.status === "failed" ? "error" : "info"}
          showIcon
          message={`官网价格同步：${collectionJob.status}`}
          description={`已处理 ${collectionJob.progress.completed ?? 0} / ${
            collectionJob.progress.total ?? 0
          } 个模型；等待 ${collectionJob.progress.pending ?? 0}，采集中 ${
            collectionJob.progress.running ?? 0
          }，官方 ${collectionJob.progress.official ?? 0}，AI候选 ${
            collectionJob.progress.ai ?? 0
          }，失败 ${
            collectionJob.progress.failed ?? 0
          }。同步不受15分钟解锁倒计时限制。`}
        />
      )}
      {collectionJob?.items?.length ? (
        <Table
          size="small"
          rowKey="id"
          dataSource={collectionJob.items}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "平台", dataIndex: "provider_id" },
            { title: "模型", dataIndex: "model_key" },
            { title: "区域", dataIndex: "pricing_region" },
            { title: "同步状态", dataIndex: "status" },
            { title: "失败原因", dataIndex: "error_summary" },
          ]}
        />
      ) : null}
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
        <Button onClick={() => void initialize()}>生成价格草案</Button>
        <Button
          loading={Boolean(
            collectionJob &&
              ["pending", "running"].includes(collectionJob.status),
          )}
          onClick={() => void collectOfficialPricing()}
        >
          同步官网价格
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
        <Button onClick={() => void exportExcel()}>
          {draft ? "下载价格草案" : "导出当前价格"}
        </Button>
        <Button
          disabled={!activeUnlock}
          onClick={async () => {
            if (!activeUnlock) return;
            const result = await billingApi.refreshOfficialPricingCandidates(
              activeUnlock.token,
            );
            message.success(`已刷新 ${result.candidate_count} 条官方候选价格`);
          }}
        >
          刷新官方候选
        </Button>
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
              new Set(
                draft?.rows.map(
                  (row) => `${row.provider_id}/${row.model_key}`,
                ) ?? [],
              ).size
            })`,
            children: (
              <PricingDrafts
                catalogs={overview.catalogs}
                draft={draft}
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
                onMapping={async (
                  providerId,
                  modelKey,
                  officialProviderId,
                  officialModelId,
                ) => {
                  if (!activeUnlock) return;
                  await billingApi.savePricingModelMapping(
                    providerId,
                    modelKey,
                    officialProviderId,
                    officialModelId,
                    mappings.find(
                      (item) =>
                        item.provider_id === providerId &&
                        item.model_key === modelKey,
                    )?.revision ?? 0,
                    activeUnlock.token,
                  );
                  setDraft(await billingApi.generatePricingDraft());
                  setMappings(await billingApi.listPricingModelMappings());
                  message.success("官方模型精确映射已保存，草案已重新生成");
                }}
                onModelDecision={async (
                  providerId,
                  modelKey,
                  includeInPublish,
                  reason,
                ) => {
                  if (!activeUnlock || !draft) return;
                  await billingApi.setPricingModelDecisions(
                    draft.draft_key,
                    [
                      {
                        provider_id: providerId,
                        model_key: modelKey,
                        include_in_publish: includeInPublish,
                        reason,
                      },
                    ],
                    activeUnlock.token,
                  );
                  setDraft(await billingApi.generatePricingDraft());
                  message.success("模型本次发布状态已保存");
                }}
                onBatchDecision={async (
                  includeInPublish,
                  evidenceLevels,
                  reason,
                ) => {
                  if (!activeUnlock || !draft) return;
                  const result = (await billingApi.batchSetPricingModelDecision(
                    draft.draft_key,
                    {
                      include_in_publish: includeInPublish,
                      evidence_levels: evidenceLevels,
                      reason,
                    },
                    activeUnlock.token,
                  )) as { updated_models?: number };
                  setDraft(await billingApi.generatePricingDraft());
                  message.success(
                    `已更新 ${result.updated_models ?? 0} 个模型的发布状态`,
                  );
                }}
                onExclusion={async (providerId, modelKey, excluded, reason) => {
                  if (!activeUnlock || !draft) return;
                  await billingApi.setPricingExclusion(
                    draft.draft_key,
                    providerId,
                    modelKey,
                    excluded,
                    reason,
                    activeUnlock.token,
                  );
                  setDraft(await billingApi.generatePricingDraft());
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
