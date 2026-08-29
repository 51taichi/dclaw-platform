import { Alert, Card, Descriptions } from "antd";

export default function PricingRules() {
  return (
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
  );
}
