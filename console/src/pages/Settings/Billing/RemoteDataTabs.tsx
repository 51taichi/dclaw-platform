import { useEffect, useState } from "react";
import { Alert, Button, Card, Radio, Space, Table } from "antd";
import { billingApi } from "../../../api/modules/billing";

function JsonRows({ load }: { load: () => Promise<unknown> }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string>();
  useEffect(() => {
    void load()
      .then((value) => {
        const data = value as
          | { items?: Record<string, unknown>[] }
          | Record<string, unknown>[];
        setRows(Array.isArray(data) ? data : data.items ?? []);
      })
      .catch((reason) => setError(String(reason)));
  }, [load]);
  if (error) return <Alert type="error" message={error} />;
  return (
    <Table
      rowKey={(row) => String(row.id ?? row.public_id ?? JSON.stringify(row))}
      dataSource={rows}
      columns={[
        {
          title: "记录",
          render: (_, row) => <pre>{JSON.stringify(row, null, 2)}</pre>,
        },
      ]}
    />
  );
}

export const PricingTab = () => <JsonRows load={billingApi.listCatalogs} />;
export const UsageTab = () => <JsonRows load={billingApi.listAdminUsage} />;
export const ReconciliationTab = () => (
  <Space direction="vertical" style={{ width: "100%" }}>
    <Card title="待对账">
      <JsonRows load={billingApi.listReconciliation} />
    </Card>
    <Card title="不可变审计">
      <JsonRows load={billingApi.listReconciliationAudits} />
    </Card>
  </Space>
);

export function RolloutTab() {
  const [mode, setMode] = useState<"off" | "shadow" | "observe" | "enforced">(
    "shadow",
  );
  const [current, setCurrent] = useState<Record<string, unknown>>({});
  useEffect(() => {
    void billingApi.getRollout().then(setCurrent);
  }, []);
  return (
    <Card title="计费灰度">
      <p>当前：{String(current.mode ?? "未激活")}</p>
      <Radio.Group
        value={mode}
        onChange={(event) => setMode(event.target.value)}
        options={["off", "shadow", "observe", "enforced"]}
      />
      <Button
        onClick={() => void billingApi.activateRollout(mode).then(setCurrent)}
      >
        确认切换
      </Button>
    </Card>
  );
}
