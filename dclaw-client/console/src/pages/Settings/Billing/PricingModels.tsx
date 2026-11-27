import { Table, Tag } from "antd";
import type {
  PriceableModel,
  PricingCatalogSummary,
} from "../../../api/types/billing";

const categoryLabels: Record<string, string> = {
  text: "文本/多模态对话",
  image: "图片生成与编辑",
  video: "视频生成",
  audio: "音频/语音",
  embedding_rerank: "Embedding 与重排",
  other: "其他模型",
};

export default function PricingModels({
  models,
  catalogs,
}: {
  models: PriceableModel[];
  catalogs: PricingCatalogSummary[];
}) {
  const active = catalogs.find((item) => item.status === "published");
  return (
    <Table
      rowKey={(row) => `${row.provider_id}/${row.model_key}`}
      dataSource={models}
      pagination={false}
      columns={[
        { title: "供应商", dataIndex: "provider_name" },
        {
          title: "分类",
          dataIndex: "category",
          render: (value) => categoryLabels[value] ?? value,
        },
        {
          title: "模型",
          dataIndex: "model_name",
          render: (value, row) => (
            <>
              <div>{value}</div>
              <small>{row.model_key}</small>
            </>
          ),
        },
        {
          title: "人民币成本与积分价格",
          render: (_, row) => {
            const rules =
              active?.rules?.filter(
                (rule) =>
                  rule.provider_id === row.provider_id &&
                  rule.model_key === row.model_key,
              ) ?? [];
            return rules.length ? (
              rules.map((rule) => {
                const metadata = rule.metadata;
                const policy = `${String(metadata.applied_multiplier ?? "-")}倍（${String(
                  metadata.multiplier_scope ?? "-",
                )}: ${String(metadata.multiplier_scope_key ?? "-")}）`;
                return rule.unit_type === "tokens" ? (
                  <div key={rule.id}>
                    <div>
                      输入：成本 ¥{String(metadata.input_rmb_cost ?? "-")} →
                      售价 ¥{String(metadata.input_rmb_sale_price ?? "-")} / 1K ·
                      {rule.input_credits_per_1k}积分
                    </div>
                    <div>
                      输出：成本 ¥{String(metadata.output_rmb_cost ?? "-")} →
                      售价 ¥{String(metadata.output_rmb_sale_price ?? "-")} / 1K ·
                      {rule.output_credits_per_1k}积分
                    </div>
                    <small>
                      风险缓冲 {String(metadata.risk_buffer ?? "-")} · 生效倍率 {policy}
                    </small>
                  </div>
                ) : (
                  <div key={rule.id}>
                    成本 ¥{String(metadata.rmb_cost ?? "-")} → 售价 ¥
                    {String(metadata.rmb_sale_price ?? "-")} / {rule.unit_type} ·
                    {rule.credits_per_unit}积分
                    <br />
                    <small>
                      风险缓冲 {String(metadata.risk_buffer ?? "-")} · 生效倍率 {policy}
                    </small>
                  </div>
                );
              })
            ) : (
              <Tag color="warning">待配置可信成本</Tag>
            );
          },
        },
      ]}
    />
  );
}
