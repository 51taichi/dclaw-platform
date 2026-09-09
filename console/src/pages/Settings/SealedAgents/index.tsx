import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Avatar,
  Button,
  Card,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import {
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
  type SuperExpertGrantPreview,
} from "../../../api/modules/sealedAgents";
import { useAppMessage } from "../../../hooks/useAppMessage";
import SuperExpertBadge from "../../../components/SuperExpertBadge";
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

function activationErrorMessage(error: unknown) {
  if (!(error instanceof Error)) return "激活失败";

  const separator = " - ";
  const separatorIndex = error.message.lastIndexOf(separator);
  if (separatorIndex < 0) return error.message;

  try {
    JSON.parse(error.message.slice(separatorIndex + separator.length));
    return error.message.slice(0, separatorIndex);
  } catch {
    return error.message;
  }
}

export default function SealedAgentsPage() {
  const { message } = useAppMessage();
  const [agents, setAgents] = useState<SealedAgentOperational[]>([]);
  const [selectedReleaseIds, setSelectedReleaseIds] = useState<
    Record<string, string>
  >({});
  const [loading, setLoading] = useState(false);
  const [grantPreview, setGrantPreview] =
    useState<SuperExpertGrantPreview | null>(null);
  const [grantSubmitting, setGrantSubmitting] = useState(false);

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
      const uploaded = await sealedAgentsApi.uploadRelease(file as File);
      message.success("密封发布包已验证并暂存");
      onSuccess?.({});
      if (uploaded.package_type === "super_expert") {
        const preview = await sealedAgentsApi.previewGrant(
          uploaded.agent_id,
          uploaded.release_id,
        );
        setGrantPreview(preview);
        return;
      }
      await load();
    } catch (error) {
      onError?.(error as Error);
      message.error(error instanceof Error ? error.message : "上传失败");
    }
  };

  return (
    <div className={styles.page}>
      <Modal
        open={grantPreview !== null}
        title="超级专家能力授权"
        closable={false}
        maskClosable={false}
        keyboard={false}
        cancelText="取消"
        okText="全部授权并安装"
        confirmLoading={grantSubmitting}
        onCancel={async () => {
          if (!grantPreview || grantSubmitting) return;
          setGrantSubmitting(true);
          try {
            await sealedAgentsApi.cancelGrant(
              grantPreview.agent_id,
              grantPreview.release_id,
            );
            setGrantPreview(null);
            await load();
          } catch (error) {
            message.error(error instanceof Error ? error.message : "取消失败");
          } finally {
            setGrantSubmitting(false);
          }
        }}
        onOk={async () => {
          if (!grantPreview) return;
          setGrantSubmitting(true);
          try {
            await sealedAgentsApi.acceptGrant(
              grantPreview.agent_id,
              grantPreview.release_id,
            );
            await sealedAgentsApi.activate(
              grantPreview.agent_id,
              grantPreview.release_id,
            );
            message.success("超级专家已完成整包授权并安装");
            setGrantPreview(null);
            await load();
          } catch (error) {
            message.error(activationErrorMessage(error));
          } finally {
            setGrantSubmitting(false);
          }
        }}
      >
        {grantPreview ? (
          <div className={styles.grantPreview}>
            <Alert
              type="success"
              showIcon
              message="官方超级专家签名"
              description="以下是该签名包声明的完整能力集合。授权按整个签名包生效，不能拆分或临时增减。"
            />
            <div className={styles.capabilityList}>
              {grantPreview.capabilities.map(([capability, version]) => (
                <div
                  className={styles.capabilityItem}
                  key={`${capability}:${version}`}
                >
                  <Typography.Text code>{capability}</Typography.Text>
                  <Tag>v{version}</Tag>
                </div>
              ))}
            </div>
            <Typography.Text type="secondary">
              能力摘要：{grantPreview.capability_digest}
            </Typography.Text>
          </div>
        ) : null}
      </Modal>
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
                    <Avatar src={a.avatar}>{a.name.charAt(0)}</Avatar>
                    <SuperExpertBadge />
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
                          try {
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
                          } catch (error) {
                            message.error(activationErrorMessage(error));
                          }
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
                  <Upload
                    accept="image/png,image/jpeg,image/webp"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      if (file.size > 2 * 1024 * 1024) {
                        message.error("头像不能超过 2 MB");
                        return Upload.LIST_IGNORE;
                      }
                      return true;
                    }}
                    customRequest={async ({ file, onSuccess, onError }) => {
                      try {
                        const updated = await sealedAgentsApi.uploadAvatar(
                          agent.agent_id,
                          file as File,
                        );
                        setAgents((items) =>
                          items.map((item) =>
                            item.agent_id === updated.agent_id ? updated : item,
                          ),
                        );
                        window.dispatchEvent(
                          new Event("expert-avatar-updated"),
                        );
                        message.success("头像已保存，升级版本时会自动保留");
                        onSuccess?.({});
                      } catch (error) {
                        onError?.(error as Error);
                        message.error(
                          error instanceof Error
                            ? error.message
                            : "头像上传失败",
                        );
                      }
                    }}
                  >
                    <button
                      type="button"
                      className={styles.avatarUpload}
                      aria-label={`${agent.avatar ? "更换" : "上传"}${
                        agent.name
                      }头像`}
                      title="点击上传头像（PNG、JPEG、WebP，最大 2 MB）"
                    >
                      <Avatar size={64} src={agent.avatar}>
                        {agent.name.charAt(0)}
                      </Avatar>
                      <span>{agent.avatar ? "更换头像" : "上传头像"}</span>
                    </button>
                  </Upload>
                  <div className={styles.expertDescription}>
                    <Space>
                      <Typography.Text strong>{agent.name}</Typography.Text>
                      <SuperExpertBadge />
                    </Space>
                    <Typography.Paragraph
                      style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}
                    >
                      {agent.description || "暂无专家介绍"}
                    </Typography.Paragraph>
                  </div>
                </div>
              ),
            }}
          />
        </Card>
      </div>
    </div>
  );
}
