import { useState } from "react";
import { Button, Input, Modal, Space, Switch, Table, Tag } from "antd";
import type {
  PricingCatalogSummary,
  PricingDraft,
} from "../../../api/types/billing";

const sourceLabels: Record<string, string> = {
  official_registry: "内置官方价目",
  trusted_cost: "已核验成本",
  missing: "暂无价格来源",
};

const verificationLabels: Record<string, string> = {
  verified: "已核验",
  candidate: "候选待审批",
  unmatched: "模型未匹配",
  missing: "缺少价格",
};

const evidenceLabels: Record<string, string> = {
  official_verified: "官方核验价格",
  ai_official_extract: "AI 提取官网价格（待审批）",
  ai_multi_source: "AI 多来源估算（待审批）",
  ai_no_evidence: "AI 无证据估算（默认不发布）",
  failed: "采集失败",
};

export default function PricingDrafts({
  catalogs,
  draft,
  canMutate = false,
  onRollback,
  onPublish,
  onExclusion,
  onMapping,
  onModelDecision,
  onBatchDecision,
}: {
  catalogs: PricingCatalogSummary[];
  draft?: PricingDraft;
  canMutate?: boolean;
  onRollback?: (id: string) => void;
  onPublish?: (id: string) => void;
  onExclusion?: (
    providerId: string,
    modelKey: string,
    excluded: boolean,
    reason: string | null,
  ) => Promise<void>;
  onMapping?: (
    providerId: string,
    modelKey: string,
    officialProviderId: string,
    officialModelId: string,
  ) => Promise<void>;
  onModelDecision?: (
    providerId: string,
    modelKey: string,
    includeInPublish: boolean,
    reason: string | null,
  ) => Promise<void>;
  onBatchDecision?: (
    includeInPublish: boolean,
    evidenceLevels: string[],
    reason: string | null,
  ) => Promise<void>;
}) {
  const [pending, setPending] = useState<{
    providerId: string;
    modelKey: string;
  }>();
  const [reason, setReason] = useState("");
  const [mapping, setMapping] = useState<{
    providerId: string;
    modelKey: string;
    officialProviderId: string;
    officialModelId: string;
  }>();
  const [decision, setDecision] = useState<{
    providerId: string;
    modelKey: string;
    includeInPublish: boolean;
    requiresReason: boolean;
  }>();
  const [decisionReason, setDecisionReason] = useState("");
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {draft && (
        <Space wrap>
          <Button
            disabled={!canMutate}
            onClick={() =>
              void onBatchDecision?.(
                true,
                ["official_verified"],
                "官方可信价格批量纳入",
              )
            }
          >
            官方可信模型全部发布
          </Button>
          <Button
            disabled={!canMutate}
            onClick={() =>
              void onBatchDecision?.(
                false,
                [
                  "ai_official_extract",
                  "ai_multi_source",
                  "ai_no_evidence",
                  "failed",
                ],
                "价格证据待人工复核",
              )
            }
          >
            模糊价格模型全部不发布
          </Button>
        </Space>
      )}
      {draft && (
        <Table
          rowKey={(row) =>
            `${row.provider_id}/${row.model_key}/${row.capability}/${
              row.unit_key
            }/${row.unit_size}/${JSON.stringify(row.conditions)}`
          }
          dataSource={draft.rows}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: "平台", dataIndex: "provider_name" },
            { title: "模型", dataIndex: "model_name" },
            { title: "能力", dataIndex: "capability" },
            { title: "计价维度", dataIndex: "unit_key" },
            {
              title: "单位/条件",
              render: (_, row) => (
                <span>
                  每 {row.unit_size} · {JSON.stringify(row.conditions)}
                </span>
              ),
            },
            {
              title: "官方成本",
              render: (_, row) =>
                row.rmb_cost == null ? "待补充" : `¥${row.rmb_cost}`,
            },
            {
              title: "默认售价",
              render: (_, row) =>
                row.rmb_sale_price == null
                  ? "-"
                  : `¥${row.rmb_sale_price} · ${row.credits}积分`,
            },
            {
              title: "来源",
              render: (_, row) => (
                <Space direction="vertical" size={0}>
                  {row.source_url ? (
                    <a href={row.source_url} target="_blank" rel="noreferrer">
                      {sourceLabels[row.source_type] ?? row.source_type} /{" "}
                      {verificationLabels[row.verification_status] ??
                        row.verification_status}
                    </a>
                  ) : (
                    <span>
                      {sourceLabels[row.source_type] ?? row.source_type} /{" "}
                      {verificationLabels[row.verification_status] ??
                        row.verification_status}
                    </span>
                  )}
                  <Tag>
                    {evidenceLabels[row.evidence_level ?? ""] ??
                      "价格证据待确认"}
                  </Tag>
                  {row.confidence != null ? (
                    <span>置信度：{String(row.confidence)}</span>
                  ) : null}
                  {row.ai_model ? <span>评估模型：{row.ai_model}</span> : null}
                  {row.evidence_excerpt ? (
                    <span title={row.evidence_excerpt}>
                      证据摘要：{row.evidence_excerpt.slice(0, 80)}
                    </span>
                  ) : null}
                </Space>
              ),
            },
            {
              title: "纳入状态",
              render: (_, row, index) => {
                const firstModelRow =
                  draft.rows.findIndex(
                    (candidate) =>
                      candidate.provider_id === row.provider_id &&
                      candidate.model_key === row.model_key,
                  ) === index;
                if (!firstModelRow) return null;
                if (row.exclusion_reason)
                  return (
                    <Space direction="vertical" size={4}>
                      <Switch
                        aria-label={`${row.model_name} 本次发布`}
                        checked={false}
                        checkedChildren="本次发布"
                        unCheckedChildren="本次不发布"
                        disabled={!canMutate}
                        onChange={() =>
                          void onExclusion?.(
                            row.provider_id,
                            row.model_key,
                            false,
                            null,
                          )
                        }
                      />
                      <Tag>已排除：{row.exclusion_reason}</Tag>
                    </Space>
                  );
                return (
                  <Space direction="vertical" size={4}>
                    <Switch
                      aria-label={`${row.model_name} 本次发布`}
                      checked={row.include_in_publish}
                      checkedChildren="本次发布"
                      unCheckedChildren="本次不发布"
                      disabled={!canMutate}
                      onChange={(includeInPublish) => {
                        setDecision({
                          providerId: row.provider_id,
                          modelKey: row.model_key,
                          includeInPublish,
                          requiresReason:
                            includeInPublish &&
                            row.evidence_level !== "official_verified",
                        });
                        setDecisionReason("");
                      }}
                    />
                    {!row.include_in_publish ? (
                      <>
                        <Button
                          type="link"
                          disabled={!canMutate}
                          onClick={() => {
                            setMapping({
                              providerId: row.provider_id,
                              modelKey: row.model_key,
                              officialProviderId:
                                row.official_provider_id ?? "",
                              officialModelId: row.official_model_id ?? "",
                            });
                          }}
                        >
                          配置官方精确映射
                        </Button>
                        <Button
                          type="link"
                          disabled={!canMutate}
                          onClick={() => {
                            setPending({
                              providerId: row.provider_id,
                              modelKey: row.model_key,
                            });
                            setReason("");
                          }}
                        >
                          填写原因并排除
                        </Button>
                      </>
                    ) : null}
                  </Space>
                );
              },
            },
          ]}
        />
      )}
      <Table
        rowKey="id"
        dataSource={catalogs}
        pagination={false}
        columns={[
          { title: "版本", dataIndex: "version" },
          {
            title: "状态",
            dataIndex: "status",
            render: (value) => (
              <Tag color={value === "published" ? "green" : "blue"}>
                {value === "published" ? "已发布" : "草稿"}
              </Tag>
            ),
          },
          { title: "生效时间", dataIndex: "effective_at" },
          {
            title: "操作",
            render: (_, row) =>
              row.status === "published" ? (
                <Button
                  danger
                  disabled={!canMutate}
                  onClick={() => onRollback?.(row.id)}
                >
                  回滚到此版本
                </Button>
              ) : (
                <Button
                  type="primary"
                  disabled={!canMutate}
                  onClick={() => onPublish?.(row.id)}
                >
                  审批并发布
                </Button>
              ),
          },
        ]}
      />
      <Modal
        open={Boolean(decision)}
        title={
          decision?.includeInPublish ? "确认本次发布模型" : "确认本次不发布模型"
        }
        okText="保存发布状态"
        okButtonProps={{
          disabled: Boolean(decision?.requiresReason && !decisionReason.trim()),
        }}
        onCancel={() => setDecision(undefined)}
        onOk={async () => {
          if (!decision) return;
          await onModelDecision?.(
            decision.providerId,
            decision.modelKey,
            decision.includeInPublish,
            decisionReason.trim() || null,
          );
          setDecision(undefined);
        }}
      >
        <p>
          此状态仅决定当前草案发布时该模型是否对客户可见；不会自动发布目录。
        </p>
        <Input.TextArea
          aria-label="发布决策原因"
          value={decisionReason}
          onChange={(event) => setDecisionReason(event.target.value)}
          placeholder={
            decision?.requiresReason
              ? "AI或模糊价格必须填写人工审批依据"
              : "可选：填写本次发布决策原因"
          }
          maxLength={2000}
        />
      </Modal>
      <Modal
        open={Boolean(pending)}
        title="填写模型排除原因"
        okButtonProps={{ disabled: !reason.trim() }}
        onCancel={() => setPending(undefined)}
        onOk={async () => {
          if (!pending || !reason.trim()) return;
          await onExclusion?.(
            pending.providerId,
            pending.modelKey,
            true,
            reason.trim(),
          );
          setPending(undefined);
        }}
      >
        <Input.TextArea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="例如：尚未获得可核验的官方价格，本版暂不开放"
          maxLength={2000}
        />
      </Modal>
      <Modal
        title="配置官方模型精确映射"
        open={Boolean(mapping)}
        okText="保存并重新生成草案"
        onCancel={() => setMapping(undefined)}
        onOk={async () => {
          if (!mapping) return;
          await onMapping?.(
            mapping.providerId,
            mapping.modelKey,
            mapping.officialProviderId,
            mapping.officialModelId,
          );
          setMapping(undefined);
        }}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input
            aria-label="官方平台ID"
            placeholder="例如 dashscope"
            value={mapping?.officialProviderId}
            onChange={(event) =>
              setMapping((current) =>
                current
                  ? { ...current, officialProviderId: event.target.value }
                  : current,
              )
            }
          />
          <Input
            aria-label="官方模型ID"
            placeholder="例如 qwen3-max"
            value={mapping?.officialModelId}
            onChange={(event) =>
              setMapping((current) =>
                current
                  ? { ...current, officialModelId: event.target.value }
                  : current,
              )
            }
          />
        </Space>
      </Modal>
    </Space>
  );
}
