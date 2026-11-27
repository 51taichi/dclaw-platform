import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Select,
  Switch,
  Tag,
  message,
} from "antd";

import { PageHeader } from "@/components/PageHeader";
import { request } from "../../../api";
import styles from "./index.module.less";

type ProviderKey = "lark" | "tencent";

interface CloudProviderConfig {
  provider: ProviderKey;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
  scopes: string[];
  enabled: boolean;
  authorization_url: string;
  token_url: string;
  connector_url: string;
  configured: boolean;
  updated_at?: string;
}

const providerMeta: Record<ProviderKey, { title: string; desc: string }> = {
  lark: {
    title: "飞书 / Lark",
    desc: "配置飞书开放平台应用，用户授权后使用内置官方导出任务拉取有权限的云文档。",
  },
  tencent: {
    title: "腾讯文档",
    desc: "配置腾讯文档开放能力；正文拉取需接官方 OpenAPI、MCP 或企业自有 Connector。",
  },
};

export default function MindspaceCloudSettingsPage() {
  const [providers, setProviders] = useState<CloudProviderConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);

  const fetchProviders = async () => {
    setLoading(true);
    try {
      const res = await request<{ providers: CloudProviderConfig[] }>(
        "/admin/mindspace-cloud/providers",
      );
      setProviders(res.providers || []);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "加载云文档配置失败",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  const handleSave = async (
    provider: ProviderKey,
    values: CloudProviderConfig,
  ) => {
    setSaving(provider);
    try {
      await request(`/admin/mindspace-cloud/providers/${provider}`, {
        method: "PUT",
        body: JSON.stringify({
          client_id: values.client_id || "",
          client_secret: values.client_secret || undefined,
          redirect_uri: values.redirect_uri || "",
          scopes: values.scopes || [],
          enabled: Boolean(values.enabled),
          authorization_url: values.authorization_url || "",
          token_url: values.token_url || "",
          connector_url: values.connector_url || "",
        }),
      });
      message.success("云文档应用配置已保存");
      fetchProviders();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader parent="设置" current="云文档应用配置" />
      <div className={styles.content}>
        <Alert
          type="info"
          showIcon
          message="这里配置系统级平台应用，不保存某个用户的文档权限。飞书默认由 QwenPaw 内置官方导出链路使用当前用户 token 拉取；腾讯文档需配置官方 OpenAPI/MCP/企业 Connector。"
        />

        {providers.map((provider) => (
          <Card
            key={provider.provider}
            className={styles.providerCard}
            loading={loading}
            title={
              <div className={styles.providerHeader}>
                <div>
                  <h3 className={styles.providerTitle}>
                    {providerMeta[provider.provider].title}
                  </h3>
                  <p className={styles.providerDesc}>
                    {providerMeta[provider.provider].desc}
                  </p>
                </div>
                <Tag color={provider.configured ? "green" : "default"}>
                  {provider.configured ? "已配置" : "未配置"}
                </Tag>
              </div>
            }
          >
            <Form
              layout="vertical"
              initialValues={{
                ...provider,
                client_secret: "",
              }}
              onFinish={(values) => handleSave(provider.provider, values)}
            >
              <div className={styles.formGrid}>
                <Form.Item name="enabled" label="启用" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item
                  name="client_id"
                  label="Client ID / App ID"
                  rules={[{ required: true, message: "请输入应用 ID" }]}
                >
                  <Input placeholder="平台应用 Client ID" />
                </Form.Item>
                <Form.Item name="client_secret" label="Client Secret">
                  <Input.Password placeholder="留空则保留已有密钥" />
                </Form.Item>
                <Form.Item
                  name="redirect_uri"
                  label="OAuth Redirect URI"
                  rules={[{ required: true, message: "请输入 OAuth 回调地址" }]}
                >
                  <Input placeholder="https://your-domain/api/mindspace-cloud/oauth/callback/lark" />
                </Form.Item>
                <Form.Item name="authorization_url" label="Authorization URL">
                  <Input placeholder="平台 OAuth 授权地址；飞书可留空使用默认值" />
                </Form.Item>
                <Form.Item name="token_url" label="Token URL">
                  <Input placeholder="平台 OAuth token 换取/刷新地址；飞书可留空使用默认值" />
                </Form.Item>
                <Form.Item
                  className={styles.full}
                  name="scopes"
                  label="授权 Scopes"
                >
                  <Select
                    mode="tags"
                    tokenSeparators={[",", " "]}
                    placeholder="例如 docs:read drive:read"
                  />
                </Form.Item>
                <Form.Item
                  className={styles.full}
                  name="connector_url"
                  label="外部正文 Connector URL（可选）"
                  extra="飞书可留空使用内置官方导出；腾讯文档需要配置官方 OpenAPI/MCP/企业 Connector 后才会拉取真实正文。外部服务也必须使用当前用户 access_token 拉正文。"
                >
                  <Input placeholder="可选：https://your-backend/connectors/cloud-docs/fetch" />
                </Form.Item>
              </div>

              <Button
                type="primary"
                htmlType="submit"
                loading={saving === provider.provider}
              >
                保存 {providerMeta[provider.provider].title}
              </Button>
            </Form>
          </Card>
        ))}
      </div>
    </div>
  );
}
