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
              rules.map((rule) => (
                <div key={rule.id}>
                  ¥
                  {String(
                    rule.metadata.input_rmb_sale_price ??
                      rule.metadata.rmb_sale_price ??
                      "-",
                  )}{" "}
                  / {rule.unit_type} ·{" "}
                  {rule.input_credits_per_1k || rule.credits_per_unit}积分
                </div>
              ))
            ) : (
              <Tag color="warning">待配置可信成本</Tag>
            );
          },
        },
      ]}
    />
  );
}
