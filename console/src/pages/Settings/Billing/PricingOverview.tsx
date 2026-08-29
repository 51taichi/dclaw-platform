import { Alert, Card, Col, Row, Statistic } from "antd";
import type { PricingOverview as Overview } from "../../../api/types/billing";

export default function PricingOverview({ value }: { value: Overview }) {
  const coverage = value.enabled_models
    ? Math.round((value.covered_models / value.enabled_models) * 100)
    : 0;
  const published = value.catalogs.find((item) => item.status === "published");
  return (
    <>
      {!published && (
        <Alert
          type="error"
          showIcon
          message="尚无已发布价格目录"
          description="请补齐可信人民币成本后生成首份价格草稿。"
        />
      )}
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="已启用模型" value={value.enabled_models} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="可信成本覆盖" value={coverage} suffix="%" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待处理草稿"
              value={value.catalogs.filter((x) => x.status === "draft").length}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="当前目录"
              value={published?.version ?? "未发布"}
            />
          </Card>
        </Col>
      </Row>
    </>
  );
}
