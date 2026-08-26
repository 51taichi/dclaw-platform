import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Space, Table, Tag, Typography, Upload } from "antd";
import type { UploadProps } from "antd";
import { LockKeyhole, RefreshCw, UploadCloud } from "lucide-react";
import { PageHeader } from "../../../components/PageHeader";
import {
  sealedAgentsApi,
  type SealedAgentOperational,
  type SealedRelease,
} from "../../../api/modules/sealedAgents";
import { useAppMessage } from "../../../hooks/useAppMessage";

export default function SealedAgentsPage() {
  const { message } = useAppMessage();
  const [agents, setAgents] = useState<SealedAgentOperational[]>([]);
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
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <PageHeader
        parent="设置"
        current="密封全局 Agent"
        subRow={
          <Typography.Text type="secondary">
            仅展示运行状态与签名信息；提示词、Skill、源码和下载入口不会暴露给后台管理员。
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
      <Alert
        type="info"
        showIcon
        message="密封 Agent 是可选能力，可配置 0 个或多个；普通 Agent 不受影响。"
      />
      <Table
        rowKey="agent_id"
        loading={loading}
        dataSource={agents}
        columns={[
          {
            title: "Agent",
            render: (_, a) => (
              <Space>
                <LockKeyhole size={16} />
                <span>{a.name}</span>
                <Typography.Text type="secondary">{a.agent_id}</Typography.Text>
              </Space>
            ),
          },
          { title: "版本", dataIndex: "version", render: (v) => v || "未激活" },
          {
            title: "状态",
            render: (_, a) => (
              <Tag color={a.availability === "available" ? "green" : "default"}>
                {a.availability}
              </Tag>
            ),
          },
          { title: "签名者", dataIndex: "signer_id", render: (v) => v || "-" },
          {
            title: "操作",
            render: (_, agent) => (
              <Space wrap>
                {agent.releases
                  .filter(
                    (r: SealedRelease) =>
                      r.release_id !== agent.active_release_id,
                  )
                  .map((release) => (
                    <Button
                      key={release.release_id}
                      size="small"
                      onClick={async () => {
                        await sealedAgentsApi.activate(
                          agent.agent_id,
                          release.release_id,
                        );
                        message.success(`已激活 ${release.version}`);
                        await load();
                      }}
                    >
                      激活 {release.version}
                    </Button>
                  ))}
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
            ),
          },
        ]}
        expandable={{
          expandedRowRender: (agent) => (
            <Space direction="vertical">
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
            </Space>
          ),
        }}
      />
    </Space>
  );
}
