import { ReloadOutlined } from "@ant-design/icons";
import { SparkAdvancedMonitoringLine } from "@agentscope-ai/icons";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Progress,
  Space,
  Table,
  Tooltip,
  Typography,
} from "antd";
import { useCallback, useState } from "react";
import { getConcurrencySnapshot } from "../../api/modules/concurrency";
import type { ConcurrencySnapshot } from "./types";

export type { ConcurrencySnapshot } from "./types";

interface ConcurrencyMonitorButtonProps {
  loadSnapshot?: () => Promise<ConcurrencySnapshot>;
}

function percent(current: number, maximum: number): number {
  if (maximum <= 0) return 0;
  return Math.min(100, Math.round((current / maximum) * 100));
}

function SummaryCard({
  title,
  current,
  maximum,
  detail,
}: {
  title: string;
  current: number;
  maximum: number;
  detail?: string;
}) {
  return (
    <Card size="small">
      <Typography.Text type="secondary">{title}</Typography.Text>
      <div style={{ marginTop: 8, fontSize: 24, fontWeight: 600 }}>
        {current} / {maximum}
      </div>
      <Progress
        percent={percent(current, maximum)}
        showInfo={false}
        size="small"
        status={current >= maximum ? "exception" : "normal"}
      />
      {detail && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {detail}
        </Typography.Text>
      )}
    </Card>
  );
}

export default function ConcurrencyMonitorButton({
  loadSnapshot = getConcurrencySnapshot,
}: ConcurrencyMonitorButtonProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [snapshot, setSnapshot] = useState<ConcurrencySnapshot>();
  const [error, setError] = useState<string>();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setSnapshot(await loadSnapshot());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "并发数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [loadSnapshot]);

  const showDrawer = () => {
    setOpen(true);
    void refresh();
  };

  const breakdownColumns = [
    { title: "对象", dataIndex: "label", key: "label" },
    { title: "执行中", dataIndex: "running", key: "running", width: 76 },
    { title: "排队", dataIndex: "waiting", key: "waiting", width: 64 },
    {
      title: "上限",
      dataIndex: "max_running",
      key: "max_running",
      width: 64,
    },
  ];

  const agentRows =
    snapshot?.open_api.by_agent.map((item) => ({
      ...item,
      key: item.agent_id,
      label: item.agent_id,
    })) ?? [];
  const apiKeyRows =
    snapshot?.open_api.by_api_key.map((item, index) => ({
      ...item,
      key: `${item.api_key}-${index}`,
      label: item.api_key,
    })) ?? [];

  return (
    <>
      <Tooltip title="并发监控">
        <Button
          type="text"
          icon={<SparkAdvancedMonitoringLine />}
          aria-label="并发监控"
          onClick={showDrawer}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 32,
            height: 32,
            padding: 0,
            verticalAlign: "middle",
            transform: "translateY(-3px)",
          }}
        />
      </Tooltip>
      <Drawer
        title="并发监控"
        width={560}
        open={open}
        onClose={() => setOpen(false)}
        extra={
          <Button
            icon={<ReloadOutlined />}
            aria-label="刷新"
            onClick={() => void refresh()}
            loading={loading}
          >
            刷新
          </Button>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {error && <Alert type="error" showIcon message={error} />}
          {snapshot ? (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                  gap: 12,
                }}
              >
                <SummaryCard
                  title="OpenAPI 执行"
                  current={snapshot.open_api.running}
                  maximum={snapshot.open_api.max_running}
                  detail={`当前排队 ${snapshot.open_api.waiting}`}
                />
                <SummaryCard
                  title="平台任务"
                  current={snapshot.platform_tasks.running}
                  maximum={snapshot.platform_tasks.max_running}
                />
                <SummaryCard
                  title="模型并发"
                  current={snapshot.model_calls.running}
                  maximum={snapshot.model_calls.max_running}
                />
              </div>

              <Card size="small" title="排队规则">
                <Space size="large" wrap>
                  <Typography.Text>
                    单 Agent 最多排队 {snapshot.open_api.max_waiting_per_agent}
                  </Typography.Text>
                  <Typography.Text>
                    单 Key 最多排队 {snapshot.open_api.max_waiting_per_api_key}
                  </Typography.Text>
                  <Typography.Text>
                    超时 {snapshot.open_api.wait_timeout_seconds} 秒
                  </Typography.Text>
                </Space>
              </Card>

              <Card size="small" title="按 Agent">
                {agentRows.length ? (
                  <Table
                    columns={breakdownColumns}
                    dataSource={agentRows}
                    pagination={false}
                    size="small"
                  />
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无占用"
                  />
                )}
              </Card>

              <Card size="small" title="按 API Key">
                {apiKeyRows.length ? (
                  <Table
                    columns={breakdownColumns}
                    dataSource={apiKeyRows}
                    pagination={false}
                    size="small"
                  />
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无占用"
                  />
                )}
              </Card>

              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                数据时间：{new Date(snapshot.sampled_at).toLocaleString()}
              </Typography.Text>
            </>
          ) : (
            !loading && <Empty description="暂无并发数据" />
          )}
        </Space>
      </Drawer>
    </>
  );
}
