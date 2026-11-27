import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type {
  PricingCatalogSummary,
  PricingPolicy,
  PricingPolicyInput,
} from "../../../api/types/billing";

function modelIdentity(policy: PricingPolicy) {
  if (policy.scope_type !== "model") return undefined;
  const separator = policy.scope_key.indexOf("/");
  if (separator <= 0 || separator === policy.scope_key.length - 1) {
    return undefined;
  }
  return {
    provider_id: policy.scope_key.slice(0, separator),
    model_key: policy.scope_key.slice(separator + 1),
  };
}

export default function PricingRules({
  disabled = true,
  policies = [],
  catalogs = [],
  unpublishingModel,
  onSave,
  onUnpublish,
}: {
  disabled?: boolean;
  policies?: PricingPolicy[];
  catalogs?: PricingCatalogSummary[];
  unpublishingModel?: string;
  onSave?: (value: PricingPolicyInput) => Promise<void>;
  onUnpublish?: (providerId: string, modelKey: string) => Promise<void>;
}) {
  const [form] = Form.useForm<PricingPolicyInput>();
  const activeCatalog = catalogs.find(
    (catalog) => catalog.status === "published",
  );
  const publishedModels = new Set(
    (activeCatalog?.rules ?? []).map(
      (rule) => `${rule.provider_id}/${rule.model_key}`,
    ),
  );
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Card title="默认安全规则">
        <Alert
          type="info"
          showIcon
          message="越具体的规则优先：单模型 → 分类 → 供应商 → 全局"
        />
        <Descriptions
          column={3}
          items={[
            { key: "credits", label: "积分兑换", children: "¥1 = 100积分" },
            { key: "buffer", label: "汇率风险缓冲", children: "5%" },
            { key: "floor", label: "最低销售倍数", children: "1倍" },
          ]}
        />
      </Card>
      <Card title="当前倍率规则">
        <Table
          rowKey="id"
          pagination={false}
          dataSource={policies}
          columns={[
            { title: "层级", dataIndex: "scope_type" },
            { title: "范围", dataIndex: "scope_key" },
            { title: "倍数", dataIndex: "multiplier_decimal" },
            { title: "版本", dataIndex: "revision" },
            {
              title: "状态",
              render: (_, policy: PricingPolicy) => {
                const identity = modelIdentity(policy);
                if (!identity) return "—";
                return publishedModels.has(policy.scope_key) ? (
                  <Tag color="green">已上架</Tag>
                ) : (
                  <Tag>已下架</Tag>
                );
              },
            },
            {
              title: "操作",
              render: (_, policy: PricingPolicy) => {
                const identity = modelIdentity(policy);
                const isPublished = Boolean(
                  identity && publishedModels.has(policy.scope_key),
                );
                return (
                  <Space>
                    <Button
                      disabled={disabled}
                      onClick={() =>
                        form.setFieldsValue({
                          scope_type: policy.scope_type,
                          scope_key: policy.scope_key,
                          multiplier_decimal: policy.multiplier_decimal,
                          settings: policy.settings ?? {},
                          expected_revision: policy.revision,
                        } as never)
                      }
                    >
                      编辑
                    </Button>
                    {identity && isPublished ? (
                      <Popconfirm
                        title={`确认下架 ${policy.scope_key}？`}
                        description="下架后客户页面将不再显示该模型，新请求也会被拒绝。历史账单和价格快照不受影响。"
                        okText="确认下架"
                        cancelText="取消"
                        onConfirm={() =>
                          onUnpublish?.(
                            identity.provider_id,
                            identity.model_key,
                          )
                        }
                      >
                        <Button
                          danger
                          disabled={disabled}
                          loading={unpublishingModel === policy.scope_key}
                        >
                          下架
                        </Button>
                      </Popconfirm>
                    ) : null}
                  </Space>
                );
              },
            },
          ]}
        />
      </Card>
      <Card title="新增或覆盖倍数规则">
        <Form
          form={form}
          layout="inline"
          initialValues={{
            scope_type: "global",
            scope_key: "*",
            multiplier_decimal: "1.5",
            expected_revision: 0,
          }}
          onFinish={(value) => void onSave?.(value)}
        >
          <Form.Item name="scope_type" label="层级">
            <Select
              disabled={disabled}
              style={{ width: 130 }}
              options={[
                { value: "global", label: "全局" },
                { value: "provider", label: "供应商" },
                { value: "category", label: "分类" },
                { value: "model", label: "单模型" },
              ]}
            />
          </Form.Item>
          <Form.Item name="scope_key" label="范围" rules={[{ required: true }]}>
            <Input disabled={disabled} />
          </Form.Item>
          <Form.Item
            name="multiplier_decimal"
            label="倍数"
            rules={[
              { required: true },
              {
                validator: async (_, value) => {
                  if (Number(value) < 1) throw new Error("不得低于1倍安全底价");
                },
              },
            ]}
          >
            <Input disabled={disabled} />
          </Form.Item>
          <Form.Item name="expected_revision" hidden>
            <Input />
          </Form.Item>
          <Button htmlType="submit" type="primary" disabled={disabled}>
            保存规则
          </Button>
        </Form>
      </Card>
    </Space>
  );
}
