import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Table,
} from "antd";
import type {
  PricingPolicy,
  PricingPolicyInput,
} from "../../../api/types/billing";

export default function PricingRules({
  disabled = true,
  policies = [],
  onSave,
}: {
  disabled?: boolean;
  policies?: PricingPolicy[];
  onSave?: (value: PricingPolicyInput) => Promise<void>;
}) {
  const [form] = Form.useForm<PricingPolicyInput>();
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
            { key: "floor", label: "最低销售倍数", children: "1.3倍" },
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
              title: "操作",
              render: (_, policy: PricingPolicy) => (
                <Button
                  disabled={disabled}
                  onClick={() => form.setFieldsValue({
                    scope_type: policy.scope_type,
                    scope_key: policy.scope_key,
                    multiplier_decimal: policy.multiplier_decimal,
                    settings: policy.settings ?? {},
                    expected_revision: policy.revision,
                  })}
                >
                  编辑
                </Button>
              ),
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
                  if (Number(value) < 1.3)
                    throw new Error("不得低于1.3倍安全底价");
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
