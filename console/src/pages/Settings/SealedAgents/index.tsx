import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import {
  LockKeyhole,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";
import { PageHeader } from "../../../components/PageHeader";
import {
  sealedAgentsApi,
  type SealedAgentOperational,
  type SealedRelease,
} from "../../../api/modules/sealedAgents";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

const versionCollator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

function historicalReleases(agent: SealedAgentOperational) {
  return agent.releases
    .filter((release) => release.release_id !== agent.active_release_id)
    .sort((left, right) =>
      versionCollator.compare(right.version, left.version),
    );
}

export default function SealedAgentsPage() {
  const { message } = useAppMessage();
  const [agents, setAgents] = useState<SealedAgentOperational[]>([]);
  const [selectedReleaseIds, setSelectedReleaseIds] = useState<
    Record<string, string>
  >({});
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setAgents(await sealedAgentsApi.list());
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => void load(), [load]);

  const enabledCount = agents.filter((agent) => agent.enabled).length;
  const availableCount = agents.filter(
    (agent) => agent.availability === "available",
  ).length;
  const releaseCount = agents.reduce(
    (total, agent) => total + agent.releases.length,
    0,
  );

  const upload: UploadProps["customRequest"] = async ({
    file,
    onSuccess,
    onError,
  }) => {
    try {
      await sealedAgentsApi.uploadRelease(file as File);
      message.success("密封发布包已验证并暂存");
      onSuccess?.({});
      await load();
    } catch (error) {
      onError?.(error as Error);
      message.error(error instanceof Error ? error.message : "上传失败");
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent="设置"
        current="超级专家"
        subRow={
          <Typography.Text type="secondary">
            管理只可调用、不可查看内部资产的全局 Agent 发布包。
          </Typography.Text>
        }
        extra={
          <Space>
            <Button icon={<RefreshCw size={16} />} onClick={load}>
              刷新
            </Button>
            <Upload accept=".zip" showUploadList={false} customRequest={upload}>
              <Button type="primary" icon={<UploadCloud size={16} />}>
                上传签名发布包
              </Button>
            </Upload>
          </Space>
        }
      />

      <div className={styles.content}>
        <div className={styles.summary}>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>密封 Agent</p>
            <div className={styles.summaryValue}>{agents.length}</div>
          </div>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>已启用</p>
            <div className={styles.summaryValue}>{enabledCount}</div>
          </div>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>运行可用</p>
            <div className={styles.summaryValue}>{availableCount}</div>
          </div>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>发布版本</p>
            <div className={styles.summaryValue}>{releaseCount}</div>
          </div>
        </div>

        <Alert
          className={styles.securityNotice}
          type="info"
          showIcon
          icon={<ShieldCheck size={18} />}
          message="内部资产已密封"
          description="后台仅展示运行状态与签名信息；提示词、Skill、源码、下载入口和内部追踪均不可见。该能力可配置 0 个或多个，不影响普通 Agent。"
        />

        <Card
          className={styles.tableCard}
          title={
            <Space>
              <PackageCheck size={18} />
              <span>已上传发布包</span>
              <Tag>{agents.length}</Tag>
            </Space>
          }
        >
          <Table
            rowKey="agent_id"
            loading={loading}
            dataSource={agents}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 960 }}
            locale={{ emptyText: "暂无密封 Agent，可上传签名发布包开始使用" }}
            columns={[
              {
                title: "Agent",
                render: (_, a) => (
                  <Space>
                    <LockKeyhole size={16} />
                    <span>{a.name}</span>
                    <Typography.Text type="secondary">
                      {a.agent_id}
                    </Typography.Text>
                  </Space>
                ),
              },
              {
                title: "版本",
                dataIndex: "version",
                render: (v) => v || "未激活",
              },
              {
                title: "状态",
                render: (_, a) => (
                  <Space size={4} wrap>
                    <Tag
                      color={
                        a.availability === "available" ? "green" : "default"
                      }
                    >
                      {a.availability === "available" ? "运行可用" : "不可用"}
                    </Tag>
                    <Tag color={a.enabled ? "blue" : "default"}>
                      {a.enabled ? "已启用" : "已停用"}
                    </Tag>
                  </Space>
                ),
              },
              {
                title: "签名者",
                dataIndex: "signer_id",
                render: (v) => v || "-",
              },
              {
                title: "操作",
                render: (_, agent) => {
                  const releases = historicalReleases(agent);
                  const selectedReleaseId = selectedReleaseIds[agent.agent_id];
                  return (
                    <Space wrap>
                      <Select
                        aria-label={`选择${agent.name}的历史版本`}
                        size="small"
                        value={selectedReleaseId}
                        placeholder="选择历史版本"
                        style={{ width: 140 }}
                        virtual={false}
                        disabled={releases.length === 0}
                        options={releases.map((release: SealedRelease) => ({
                          label: release.version,
                          value: release.release_id,
                        }))}
                        onChange={(releaseId) =>
                          setSelectedReleaseIds((current) => ({
                            ...current,
                            [agent.agent_id]: releaseId,
                          }))
                        }
                      />
                      <Button
                        aria-label="激活"
                        size="small"
                        disabled={!selectedReleaseId}
                        onClick={async () => {
                          const release = releases.find(
                            (item) => item.release_id === selectedReleaseId,
                          );
                          if (!release) return;
                          await sealedAgentsApi.activate(
                            agent.agent_id,
                            release.release_id,
                          );
                          message.success(`已激活 ${release.version}`);
                          setSelectedReleaseIds((current) => {
                            const next = { ...current };
                            delete next[agent.agent_id];
                            return next;
                          });
                          await load();
                        }}
                      >
                        激活
                      </Button>
                      <Button
                        size="small"
                        onClick={async () => {
                          await sealedAgentsApi.setEnabled(
                            agent.agent_id,
                            !agent.enabled,
                          );
                          await load();
                        }}
                      >
                        {agent.enabled ? "停用" : "启用"}
                      </Button>
                    </Space>
                  );
                },
              },
            ]}
            expandable={{
              expandedRowRender: (agent) => (
                <div className={styles.expandedContent}>
                  <Typography.Text>
                    {agent.description || "无公开描述"}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    内容摘要：{agent.content_digest || "-"}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    Invoke-only：允许会话与 OpenAPI
                    调用，禁止查看、编辑、克隆、导出、下载和内部追踪。
                  </Typography.Text>
                </div>
              ),
            }}
          />
        </Card>
      </div>
    </div>
  );
}
