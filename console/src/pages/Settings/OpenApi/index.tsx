import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tabs,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import {
  Ban,
  KeyRound,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { AgentExperienceLibrary } from "@/components/AgentExperienceLibrary";
import { PageHeader } from "@/components/PageHeader";
import {
  adminUsersApi,
  agentsApi,
  expertTeamsApi,
  openApiApi,
} from "../../../api";
import type {
  AdminUser,
  AgentSummary,
  ExpertTeamTemplate,
  OpenApiExternalApp,
  OpenApiInvocation,
  OpenApiKey,
  OpenApiPublication,
  OpenApiPublicationStatus,
  OpenApiScope,
  OpenApiTargetType,
} from "../../../api";
import { DEFAULT_OPEN_API_SCOPES } from "../../../api";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

interface PublicationFormValues {
  public_id: string;
  target_type: OpenApiTargetType;
  target_id: string;
  bound_user_id: number;
  title?: string;
  description?: string;
  scopes: OpenApiScope[];
  status: OpenApiPublicationStatus;
}

interface AppFormValues {
  name: string;
  ip_allowlist?: string;
}

interface KeyFormValues {
  app_id: string;
  publication_id: string;
  expires_at?: Dayjs;
  scopes: OpenApiScope[];
}

const SCOPE_OPTIONS: { label: string; value: OpenApiScope }[] = [
  { label: "messages:create", value: "messages:create" },
  { label: "messages:read", value: "messages:read" },
  { label: "runs:stop", value: "runs:stop" },
];

function getPublicationTitle(publication: OpenApiPublication) {
  return publication.title || publication.name || publication.public_id;
}

function getPublicationScopes(
  publication?: OpenApiPublication,
): OpenApiScope[] {
  if (!publication) {
    return DEFAULT_OPEN_API_SCOPES;
  }
  if (publication.scopes) {
    return publication.scopes;
  }
  if (publication.allowed_scopes) {
    return publication.allowed_scopes;
  }
  return [];
}

function getDefaultKeyScopes(publication?: OpenApiPublication): OpenApiScope[] {
  const scopes = getPublicationScopes(publication);
  if (scopes.includes("messages:create")) {
    return ["messages:create"];
  }
  return scopes.slice(0, 1);
}

function parseIpAllowlist(value?: string): string[] {
  return (value || "")
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm") : value;
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function statusTag(status?: string) {
  if (status === "enabled" || status === "active" || status === "succeeded") {
    return <Tag color="green">{status}</Tag>;
  }
  if (status === "disabled" || status === "revoked" || status === "failed") {
    return <Tag color="red">{status}</Tag>;
  }
  if (status === "running" || status === "accepted" || status === "pending") {
    return <Tag color="blue">{status}</Tag>;
  }
  if (status === "cancelled") {
    return <Tag color="orange">{status}</Tag>;
  }
  return <Tag>{status || "-"}</Tag>;
}

function keyDisplay(key: OpenApiKey) {
  if (!key.key_prefix && !key.key_suffix) return key.id;
  return `${key.key_prefix || ""}...${key.key_suffix || ""}`;
}

export default function OpenApiPage() {
  const { message } = useAppMessage();
  const [publicationForm] = Form.useForm<PublicationFormValues>();
  const [appForm] = Form.useForm<AppFormValues>();
  const [keyForm] = Form.useForm<KeyFormValues>();
  const [publications, setPublications] = useState<OpenApiPublication[]>([]);
  const [apps, setApps] = useState<OpenApiExternalApp[]>([]);
  const [keys, setKeys] = useState<OpenApiKey[]>([]);
  const [invocations, setInvocations] = useState<OpenApiInvocation[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [expertTeams, setExpertTeams] = useState<ExpertTeamTemplate[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedPublicationId, setSelectedPublicationId] = useState<string>();
  const [initialLoading, setInitialLoading] = useState(false);
  const [scopedLoading, setScopedLoading] = useState(false);
  const [creatingPublication, setCreatingPublication] = useState(false);
  const [creatingApp, setCreatingApp] = useState(false);
  const [creatingKey, setCreatingKey] = useState(false);
  const [statusBusyId, setStatusBusyId] = useState<string>();
  const [revokeBusyId, setRevokeBusyId] = useState<string>();
  const [onlyEnabled, setOnlyEnabled] = useState(true);
  const [publicationSearch, setPublicationSearch] = useState("");
  const [activeTab, setActiveTab] = useState("publications");
  const [openForm, setOpenForm] = useState<
    "publication" | "app" | "key" | null
  >(null);
  const [createdSecret, setCreatedSecret] = useState<{
    secret: string;
    keyId?: string;
  }>();

  const selectedPublication = useMemo(
    () =>
      publications.find(
        (publication) => publication.id === selectedPublicationId,
      ),
    [publications, selectedPublicationId],
  );

  const targetLabelById = useMemo(() => {
    const labels = new Map<string, string>();
    agents.forEach((agent) => labels.set(`agent:${agent.id}`, agent.name));
    expertTeams.forEach((team) =>
      labels.set(`expert_team:${team.id}`, team.name),
    );
    return labels;
  }, [agents, expertTeams]);

  const appNameById = useMemo(() => {
    const labels = new Map<string, string>();
    apps.forEach((app) => labels.set(app.id, app.name));
    return labels;
  }, [apps]);

  const publicationNameById = useMemo(() => {
    const labels = new Map<string, string>();
    publications.forEach((publication) =>
      labels.set(publication.id, getPublicationTitle(publication)),
    );
    return labels;
  }, [publications]);

  const keyScopeOptions = useMemo(
    () =>
      getPublicationScopes(selectedPublication).map((scope) => ({
        label: scope,
        value: scope,
      })),
    [selectedPublication],
  );

  const setKeyDefaults = useCallback(
    (
      publicationRows: OpenApiPublication[],
      appRows: OpenApiExternalApp[],
      publicationId?: string,
    ) => {
      const publication = publicationRows.find(
        (item) => item.id === publicationId,
      );
      keyForm.setFieldsValue({
        publication_id: publicationId,
        app_id: appRows[0]?.id,
        scopes: getDefaultKeyScopes(publication),
      });
    },
    [keyForm],
  );

  const fetchBaseData = useCallback(
    async (preferredPublicationId?: string) => {
      setInitialLoading(true);
      try {
        const [publicationRows, appRows, agentRows, teamRows, userRows] =
          await Promise.all([
            openApiApi.listPublications(),
            openApiApi.listApps(),
            agentsApi.listAgents(),
            expertTeamsApi.listAdminExpertTeams(),
            adminUsersApi.listUsers(),
          ]);
        const nextPublicationId =
          preferredPublicationId &&
          publicationRows.some((item) => item.id === preferredPublicationId)
            ? preferredPublicationId
            : publicationRows[0]?.id;

        setPublications(publicationRows);
        setApps(appRows);
        setAgents(agentRows.agents || []);
        setExpertTeams(teamRows || []);
        setUsers(userRows || []);
        if (!publicationForm.getFieldValue("bound_user_id") && userRows[0]) {
          publicationForm.setFieldValue("bound_user_id", userRows[0].id);
        }
        setSelectedPublicationId(nextPublicationId);
        setKeyDefaults(publicationRows, appRows, nextPublicationId);
      } catch (error) {
        message.error(getErrorMessage(error, "加载 Open API 配置失败"));
      } finally {
        setInitialLoading(false);
      }
    },
    [message, publicationForm, setKeyDefaults],
  );

  const fetchScopedData = useCallback(
    async (publicationId?: string) => {
      if (!publicationId) {
        setKeys([]);
        setInvocations([]);
        return;
      }

      setScopedLoading(true);
      try {
        const [keyRows, invocationRows] = await Promise.all([
          openApiApi.listKeys({ publication_id: publicationId }),
          openApiApi.listInvocations({
            publication_id: publicationId,
            limit: 50,
            offset: 0,
          }),
        ]);
        setKeys(keyRows);
        setInvocations(invocationRows);
      } catch (error) {
        message.error(getErrorMessage(error, "加载 Open API 记录失败"));
      } finally {
        setScopedLoading(false);
      }
    },
    [message],
  );

  useEffect(() => {
    publicationForm.setFieldsValue({
      target_type: "agent",
      scopes: DEFAULT_OPEN_API_SCOPES,
      status: "enabled",
    });
    keyForm.setFieldsValue({
      scopes: DEFAULT_OPEN_API_SCOPES,
    });
    void fetchBaseData();
  }, [fetchBaseData, keyForm, publicationForm]);

  useEffect(() => {
    const publication = publications.find(
      (item) => item.id === selectedPublicationId,
    );
    if (selectedPublicationId) {
      keyForm.setFieldsValue({
        publication_id: selectedPublicationId,
        scopes: getDefaultKeyScopes(publication),
      });
    }
    void fetchScopedData(selectedPublicationId);
  }, [fetchScopedData, keyForm, publications, selectedPublicationId]);

  const targetType = Form.useWatch("target_type", publicationForm) || "agent";
  const targetOptions =
    targetType === "agent"
      ? agents.map((agent) => ({
          label: agent.name || agent.id,
          value: agent.id,
        }))
      : expertTeams.map((team) => ({
          label: team.name || team.id,
          value: team.id,
        }));

  const publicationOptions = publications.map((publication) => ({
    label: `${
      targetLabelById.get(
        `${publication.target_type}:${publication.target_id}`,
      ) || getPublicationTitle(publication)
    } · ${publication.target_type === "agent" ? "专家" : "专家团"} · ${
      publication.public_id
    }`,
    value: publication.id,
  }));

  const keyPublicationOptions = publications.map((publication) => ({
    label: `${getPublicationTitle(publication)} (${publication.public_id})`,
    value: publication.id,
    disabled:
      publication.status !== "enabled" ||
      getPublicationScopes(publication).length === 0,
  }));

  const appOptions = apps.map((app) => ({
    label: app.name,
    value: app.id,
  }));

  const userOptions = users.map((user) => ({
    label: `${user.username} (${user.role})`,
    value: user.id,
  }));

  const userNameById = new Map(
    users.map((user) => [String(user.id), user.username]),
  );

  const visiblePublications = publications.filter((publication) => {
    if (onlyEnabled && publication.status !== "enabled") return false;
    const query = publicationSearch.trim().toLowerCase();
    if (!query) return true;
    const targetName =
      targetLabelById.get(
        `${publication.target_type}:${publication.target_id}`,
      ) || "";
    return [
      getPublicationTitle(publication),
      publication.public_id,
      publication.target_id,
      targetName,
    ].some((value) => value.toLowerCase().includes(query));
  });

  const handleCreatePublication = async (values: PublicationFormValues) => {
    const scopes = values.scopes || [];
    if (scopes.length === 0) {
      message.warning("发布对象至少需要一个 scope");
      return;
    }
    setCreatingPublication(true);
    try {
      const created = await openApiApi.createPublication({
        ...values,
        scopes,
        title: values.title?.trim() || undefined,
        description: values.description?.trim() || undefined,
        public_id: values.public_id.trim(),
      });
      message.success("发布对象已创建");
      setOpenForm(null);
      publicationForm.resetFields();
      publicationForm.setFieldsValue({
        target_type: "agent",
        bound_user_id: users[0]?.id,
        scopes: DEFAULT_OPEN_API_SCOPES,
        status: "enabled",
      });
      await fetchBaseData(created.id);
    } catch (error) {
      message.error(getErrorMessage(error, "创建发布对象失败"));
    } finally {
      setCreatingPublication(false);
    }
  };

  const handleCreateApp = async (values: AppFormValues) => {
    setCreatingApp(true);
    try {
      await openApiApi.createApp({
        name: values.name.trim(),
        ip_allowlist: parseIpAllowlist(values.ip_allowlist),
      });
      message.success("外部应用已创建");
      setOpenForm(null);
      appForm.resetFields();
      await fetchBaseData(selectedPublicationId);
    } catch (error) {
      message.error(getErrorMessage(error, "创建外部应用失败"));
    } finally {
      setCreatingApp(false);
    }
  };

  const handleCreateKey = async (values: KeyFormValues) => {
    if (!selectedPublication || selectedPublication.status !== "enabled") {
      message.warning("请先选择已启用的发布对象");
      return;
    }
    if (getPublicationScopes(selectedPublication).length === 0) {
      message.warning("发布对象没有可用 scope，不能创建 API Key");
      return;
    }
    const scopes = values.scopes || [];
    if (scopes.length === 0) {
      message.warning("API Key 至少需要一个 scope");
      return;
    }

    setCreatingKey(true);
    try {
      const response = await openApiApi.createKey({
        app_id: values.app_id,
        publication_id: values.publication_id,
        expires_at: values.expires_at?.toISOString() || undefined,
        scopes,
      });
      setCreatedSecret({
        secret: response.secret,
        keyId: response.key.id,
      });
      setOpenForm(null);
      message.success("API Key 已创建");
      await fetchScopedData(values.publication_id);
    } catch (error) {
      message.error(getErrorMessage(error, "创建 API Key 失败"));
    } finally {
      setCreatingKey(false);
    }
  };

  const handleStatusChange = async (publication: OpenApiPublication) => {
    const nextStatus: OpenApiPublicationStatus =
      publication.status === "enabled" ? "disabled" : "enabled";
    setStatusBusyId(publication.id);
    try {
      const updated = await openApiApi.updatePublicationStatus(
        publication.id,
        nextStatus,
      );
      setPublications((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      message.success(
        nextStatus === "enabled" ? "发布对象已启用" : "发布对象已禁用",
      );
    } catch (error) {
      message.error(getErrorMessage(error, "更新发布状态失败"));
    } finally {
      setStatusBusyId(undefined);
    }
  };

  const handleRevokeKey = async (key: OpenApiKey) => {
    setRevokeBusyId(key.id);
    try {
      const updated = await openApiApi.revokeKey(key.id);
      setKeys((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      message.success("API Key 已撤销");
    } catch (error) {
      message.error(getErrorMessage(error, "撤销 API Key 失败"));
    } finally {
      setRevokeBusyId(undefined);
    }
  };

  const publicationColumns: ColumnsType<OpenApiPublication> = [
    {
      title: "发布对象",
      key: "publication",
      width: 260,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>
            {getPublicationTitle(record)}
          </Typography.Text>
          <Typography.Text type="secondary">{record.public_id}</Typography.Text>
          <Typography.Text
            className={styles.endpointText}
            copyable={{
              text: `/api/open/v1/targets/${record.public_id}/messages`,
            }}
            type="secondary"
          >
            /api/open/v1/targets/{record.public_id}/messages
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "目标",
      key: "target",
      width: 220,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Tag color={record.target_type === "agent" ? "blue" : "purple"}>
            {record.target_type === "agent" ? "专家" : "专家团"}
          </Tag>
          <Typography.Text>
            {targetLabelById.get(`${record.target_type}:${record.target_id}`) ||
              record.target_id}
          </Typography.Text>
          {record.allowed_capability === "invoke_only" && (
            <Tag color="gold" icon={<ShieldCheck size={12} />}>
              Invoke-only · 内部资产不可见
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: "Scopes",
      key: "scopes",
      render: (_, record) => (
        <Space size={4} wrap>
          {getPublicationScopes(record).map((scope) => (
            <Tag key={scope}>{scope}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: "运行用户",
      dataIndex: "bound_user_id",
      width: 180,
      render: (userId: string) =>
        userNameById.get(String(userId)) || `用户 ${userId}`,
    },
    {
      title: "专属知识库",
      dataIndex: "knowledge_base_id",
      width: 220,
      render: (knowledgeBaseId: string) => (
        <Typography.Text copyable={{ text: knowledgeBaseId }}>
          {knowledgeBaseId}
        </Typography.Text>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: statusTag,
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 150,
      render: formatDate,
    },
    {
      title: "操作",
      key: "actions",
      width: 120,
      render: (_, record) => {
        const enabled = record.status === "enabled";
        return (
          <Button
            danger={enabled}
            icon={enabled ? <Ban size={14} /> : <RotateCcw size={14} />}
            loading={statusBusyId === record.id}
            onClick={() => void handleStatusChange(record)}
            size="small"
          >
            {enabled ? "禁用" : "启用"}
          </Button>
        );
      },
    },
  ];

  const keyColumns: ColumnsType<OpenApiKey> = [
    {
      title: "Key",
      key: "key",
      width: 180,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>
            {record.name || keyDisplay(record)}
          </Typography.Text>
          <Typography.Text type="secondary">
            {keyDisplay(record)}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "外部应用",
      dataIndex: "app_id",
      render: (appId: string) => appNameById.get(appId) || appId,
    },
    {
      title: "Scopes",
      dataIndex: "scopes",
      render: (scopes: OpenApiScope[]) => (
        <Space size={4} wrap>
          {(scopes || []).map((scope) => (
            <Tag key={scope}>{scope}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: statusTag,
    },
    {
      title: "过期时间",
      dataIndex: "expires_at",
      width: 150,
      render: formatDate,
    },
    {
      title: "最近使用",
      dataIndex: "last_used_at",
      width: 150,
      render: formatDate,
    },
    {
      title: "操作",
      key: "actions",
      width: 110,
      render: (_, record) => (
        <Popconfirm
          title="撤销 API Key"
          description="撤销后外部应用将不能继续使用这个 Key。"
          okText="撤销"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={() => void handleRevokeKey(record)}
        >
          <Button
            danger
            disabled={record.status === "revoked"}
            loading={revokeBusyId === record.id}
            size="small"
          >
            撤销
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const invocationColumns: ColumnsType<OpenApiInvocation> = [
    {
      title: "调用",
      key: "invocation",
      width: 240,
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.id}</Typography.Text>
          <Typography.Text type="secondary">
            {publicationNameById.get(record.publication_id) ||
              record.publication_id}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "外部应用",
      dataIndex: "app_id",
      render: (appId: string) => appNameById.get(appId) || appId,
    },
    {
      title: "外部用户",
      dataIndex: "external_user_id",
      render: (value?: string | null) => value || "-",
    },
    {
      title: "会话",
      dataIndex: "external_session_id",
      render: (value?: string | null) => value || "-",
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: statusTag,
    },
    {
      title: "HTTP",
      dataIndex: "status_code",
      width: 80,
      render: (value?: number | null) => value ?? "-",
    },
    {
      title: "耗时",
      dataIndex: "latency_ms",
      width: 90,
      render: (value?: number) => (value ? `${value} ms` : "-"),
    },
    {
      title: "错误",
      dataIndex: "error_summary",
      width: 220,
      render: (value?: string | null) =>
        value ? <Typography.Text type="danger">{value}</Typography.Text> : "-",
    },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 150,
      render: formatDate,
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        parent="设置"
        current="Open API"
        subRow={
          <Typography.Text type="secondary">
            统一管理对外发布、调用凭证、专属知识和调用记录。
          </Typography.Text>
        }
        extra={
          <Button
            icon={<RefreshCw size={15} />}
            loading={initialLoading || scopedLoading}
            onClick={() => void fetchBaseData(selectedPublicationId)}
          >
            刷新
          </Button>
        }
      />

      <div className={styles.content}>
        <div className={styles.summary}>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>发布对象</p>
            <div className={styles.summaryValue}>{publications.length}</div>
          </div>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>外部应用</p>
            <div className={styles.summaryValue}>{apps.length}</div>
          </div>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>当前 API Key</p>
            <div className={styles.summaryValue}>{keys.length}</div>
          </div>
          <div className={styles.summaryItem}>
            <p className={styles.summaryLabel}>已启用发布</p>
            <div className={styles.summaryValue}>
              {
                publications.filter(
                  (publication) => publication.status === "enabled",
                ).length
              }
            </div>
          </div>
        </div>

        {createdSecret ? (
          <Alert
            className={styles.secretAlert}
            type="success"
            showIcon
            closable
            onClose={() => setCreatedSecret(undefined)}
            message="一次性密钥已生成"
            description={
              <div>
                <Typography.Text type="secondary">
                  这段 secret 只会显示一次，请现在复制保存。
                </Typography.Text>
                <Typography.Text
                  className={styles.secretValue}
                  code
                  copyable={{ text: createdSecret.secret }}
                >
                  {createdSecret.secret}
                </Typography.Text>
                {createdSecret.keyId ? (
                  <Typography.Text type="secondary">
                    Key ID: {createdSecret.keyId}
                  </Typography.Text>
                ) : null}
              </div>
            }
          />
        ) : null}

        <Card className={styles.workspaceCard}>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              {
                key: "publications",
                label: "发布管理",
                children: (
                  <div className={styles.tabPanel}>
                    <div className={styles.toolbar}>
                      <Space wrap>
                        <Input.Search
                          allowClear
                          className={styles.searchInput}
                          placeholder="搜索名称、Public ID 或目标"
                          value={publicationSearch}
                          onChange={(event) =>
                            setPublicationSearch(event.target.value)
                          }
                        />
                        <Space size={6}>
                          <Switch
                            aria-label="仅显示启用"
                            checked={onlyEnabled}
                            onChange={setOnlyEnabled}
                            size="small"
                          />
                          <Typography.Text>仅显示启用</Typography.Text>
                        </Space>
                      </Space>
                      <Button
                        icon={<Plus size={15} />}
                        type="primary"
                        onClick={() => setOpenForm("publication")}
                      >
                        创建发布对象
                      </Button>
                    </div>
                    <Alert
                      className={styles.inlineNotice}
                      type="info"
                      showIcon
                      message="不再使用的接口可以先禁用；关闭“仅显示启用”即可随时查看和重新启用。"
                    />
                    <Table
                      columns={publicationColumns}
                      dataSource={visiblePublications}
                      loading={initialLoading}
                      rowKey="id"
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      scroll={{ x: 1380 }}
                    />
                  </div>
                ),
              },
              {
                key: "credentials",
                label: "应用与密钥",
                children: (
                  <div className={styles.tabPanel}>
                    <div className={styles.toolbar}>
                      <Select
                        className={styles.publicationFilter}
                        value={selectedPublicationId}
                        options={publicationOptions}
                        showSearch
                        optionFilterProp="label"
                        placeholder="选择发布对象"
                        onChange={(value) => setSelectedPublicationId(value)}
                      />
                      <Space wrap>
                        <Button
                          icon={<Plus size={15} />}
                          onClick={() => setOpenForm("app")}
                        >
                          创建外部应用
                        </Button>
                        <Button
                          icon={<KeyRound size={15} />}
                          type="primary"
                          disabled={
                            !selectedPublication ||
                            selectedPublication.status !== "enabled" ||
                            apps.length === 0
                          }
                          onClick={() => setOpenForm("key")}
                        >
                          创建 API Key
                        </Button>
                      </Space>
                    </div>
                    <div className={styles.sectionHeading}>
                      <div>
                        <Typography.Title level={5}>API Keys</Typography.Title>
                        <Typography.Text type="secondary">
                          密钥只展示前后缀；完整 secret 仅在创建后显示一次。
                        </Typography.Text>
                      </div>
                    </div>
                    <Table
                      columns={keyColumns}
                      dataSource={keys}
                      loading={scopedLoading}
                      rowKey="id"
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      scroll={{ x: 880 }}
                    />
                    <div className={styles.appList}>
                      <Typography.Title level={5}>已接入应用</Typography.Title>
                      <div className={styles.appGrid}>
                        {apps.map((app) => (
                          <div className={styles.appItem} key={app.id}>
                            <div>
                              <Typography.Text strong>
                                {app.name}
                              </Typography.Text>
                              <Typography.Text
                                type="secondary"
                                className={styles.blockText}
                              >
                                {app.ip_allowlist?.length
                                  ? `IP 限制：${app.ip_allowlist.join(", ")}`
                                  : "不限来源 IP"}
                              </Typography.Text>
                            </div>
                            {statusTag(app.status || "enabled")}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ),
              },
              {
                key: "knowledge",
                label: "专属知识库",
                children: (
                  <div className={styles.tabPanel}>
                    <AgentExperienceLibrary />
                  </div>
                ),
              },
              {
                key: "invocations",
                label: "调用记录",
                children: (
                  <div className={styles.tabPanel}>
                    <div className={styles.toolbar}>
                      <div>
                        <Typography.Title level={5}>最近调用</Typography.Title>
                        <Typography.Text type="secondary">
                          查看调用状态、耗时和错误摘要。
                        </Typography.Text>
                      </div>
                      <Select
                        className={styles.publicationFilter}
                        value={selectedPublicationId}
                        options={publicationOptions}
                        showSearch
                        optionFilterProp="label"
                        placeholder="选择发布对象"
                        onChange={(value) => setSelectedPublicationId(value)}
                      />
                    </div>
                    <Table
                      columns={invocationColumns}
                      dataSource={invocations}
                      loading={scopedLoading}
                      rowKey="id"
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      scroll={{ x: 1180 }}
                    />
                  </div>
                ),
              },
            ]}
          />
        </Card>
      </div>

      <Modal
        title="创建发布对象"
        open={openForm === "publication"}
        onCancel={() => setOpenForm(null)}
        footer={null}
        destroyOnHidden
        forceRender
      >
        <Form
          className={styles.modalForm}
          form={publicationForm}
          layout="vertical"
          onFinish={handleCreatePublication}
        >
          <Form.Item
            name="public_id"
            label="Public ID"
            rules={[{ required: true, message: "请输入 public_id" }]}
          >
            <Input placeholder="support_agent" />
          </Form.Item>
          <div className={styles.targetRow}>
            <Form.Item name="target_type" label="目标类型">
              <Select
                onChange={() =>
                  publicationForm.setFieldValue("target_id", undefined)
                }
                options={[
                  { label: "专家", value: "agent" },
                  { label: "专家团", value: "expert_team" },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="target_id"
              label="目标"
              rules={[{ required: true, message: "请选择目标" }]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择专家或专家团"
                options={targetOptions}
              />
            </Form.Item>
          </div>
          <Form.Item name="title" label="发布标题">
            <Input placeholder="客服专家" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="给外部应用识别的说明" />
          </Form.Item>
          <Form.Item
            name="bound_user_id"
            label="运行用户"
            extra="外部调用使用该用户的会话和用户配置。"
            rules={[{ required: true, message: "请选择绑定用户" }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择运行用户"
              options={userOptions}
            />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="允许 scopes"
            rules={[
              {
                required: true,
                type: "array",
                min: 1,
                message: "至少选择一个 scope",
              },
            ]}
          >
            <Select mode="multiple" options={SCOPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="初始状态">
            <Select
              options={[
                { label: "启用", value: "enabled" },
                { label: "禁用", value: "disabled" },
              ]}
            />
          </Form.Item>
          <div className={styles.actions}>
            <Button onClick={() => setOpenForm(null)}>取消</Button>
            <Button
              htmlType="submit"
              loading={creatingPublication}
              type="primary"
            >
              创建发布对象
            </Button>
          </div>
        </Form>
      </Modal>

      <Modal
        title="创建外部应用"
        open={openForm === "app"}
        onCancel={() => setOpenForm(null)}
        footer={null}
        destroyOnHidden
        forceRender
      >
        <Form
          className={styles.modalForm}
          form={appForm}
          layout="vertical"
          onFinish={handleCreateApp}
        >
          <Form.Item
            name="name"
            label="应用名称"
            rules={[{ required: true, message: "请输入应用名称" }]}
          >
            <Input placeholder="CRM / 小程序 / 内部系统" />
          </Form.Item>
          <Form.Item name="ip_allowlist" label="IP allowlist">
            <Input.TextArea
              rows={3}
              placeholder="留空表示不限 IP；多个 IP 可用逗号或换行分隔"
            />
          </Form.Item>
          <div className={styles.actions}>
            <Button onClick={() => setOpenForm(null)}>取消</Button>
            <Button htmlType="submit" loading={creatingApp} type="primary">
              创建外部应用
            </Button>
          </div>
        </Form>
      </Modal>

      <Modal
        title="创建 API Key"
        open={openForm === "key"}
        onCancel={() => setOpenForm(null)}
        footer={null}
        destroyOnHidden
        forceRender
      >
        <Form
          className={styles.modalForm}
          form={keyForm}
          layout="vertical"
          onFinish={handleCreateKey}
        >
          <Form.Item
            name="publication_id"
            label="发布对象"
            rules={[{ required: true, message: "请选择发布对象" }]}
          >
            <Select
              disabled={publications.length === 0}
              options={keyPublicationOptions}
              showSearch
              optionFilterProp="label"
              onChange={(value) => setSelectedPublicationId(value)}
            />
          </Form.Item>
          <Form.Item
            name="app_id"
            label="外部应用"
            rules={[{ required: true, message: "请选择外部应用" }]}
          >
            <Select disabled={apps.length === 0} options={appOptions} />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="Key scopes"
            rules={[
              {
                required: true,
                type: "array",
                min: 1,
                message: "至少选择一个 scope",
              },
            ]}
          >
            <Select mode="multiple" options={keyScopeOptions} />
          </Form.Item>
          <Form.Item name="expires_at" label="过期时间">
            <DatePicker showTime style={{ width: "100%" }} />
          </Form.Item>
          <div className={styles.actions}>
            <Button onClick={() => setOpenForm(null)}>取消</Button>
            <Button
              disabled={
                !selectedPublication ||
                selectedPublication.status !== "enabled" ||
                getPublicationScopes(selectedPublication).length === 0
              }
              htmlType="submit"
              loading={creatingKey}
              type="primary"
            >
              创建 API Key
            </Button>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
