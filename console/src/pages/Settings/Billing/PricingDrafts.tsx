import { useState } from "react";
import { Button, Input, Modal, Space, Table, Tag } from "antd";
import type {
  PricingCatalogSummary,
  PricingDraft,
} from "../../../api/types/billing";

export default function PricingDrafts({
  catalogs,
  draft,
  canMutate = false,
  onRollback,
  onPublish,
  onExclusion,
  onMapping,
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
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
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
              render: (_, row) =>
                row.source_url ? (
                  <a href={row.source_url} target="_blank" rel="noreferrer">
                    {row.source_type} / {row.verification_status}
                  </a>
                ) : (
                  `${row.source_type} / ${row.verification_status}`
                ),
            },
            {
              title: "纳入状态",
              render: (_, row) =>
                row.include_in_publish ? (
                  <Tag color="green">纳入</Tag>
                ) : row.exclusion_reason ? (
                  <Button
                    type="link"
                    disabled={!canMutate}
                    onClick={() =>
                      void onExclusion?.(
                        row.provider_id,
                        row.model_key,
                        false,
                        null,
                      )
                    }
                  >
                    已排除：{row.exclusion_reason}（恢复）
                  </Button>
                ) : (
                  <Space direction="vertical" size={0}>
                    <Button
                      type="link"
                      disabled={!canMutate}
                      onClick={() => {
                        setMapping({
                          providerId: row.provider_id,
                          modelKey: row.model_key,
                          officialProviderId: row.official_provider_id ?? "",
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
                  </Space>
                ),
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
