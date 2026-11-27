import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from "antd";
import { ExternalLink, Globe2, Save, Search, Wifi } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import {
  webSearchApi,
  type WebSearchConfig,
} from "../../../api/modules/webSearch";
import styles from "./index.module.less";

const IQS_ENDPOINT = "https://cloud-iqs.aliyuncs.com/search/unified";

const emptyConfig: WebSearchConfig = {
  provider: "aliyun_iqs",
  enabled: false,
  api_key: "",
  endpoint: IQS_ENDPOINT,
  engine_type: "LiteAdvanced",
  default_max_results: 5,
  timeout_seconds: 8,
  cache_ttl_seconds: 300,
  configured: false,
  available: false,
};

type EditableConfig = Pick<
  WebSearchConfig,
  | "enabled"
  | "api_key"
  | "endpoint"
  | "engine_type"
  | "default_max_results"
  | "timeout_seconds"
  | "cache_ttl_seconds"
>;

export default function WebSearchPage() {
  const [form] = Form.useForm<EditableConfig>();
  const [config, setConfig] = useState<WebSearchConfig>(emptyConfig);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const response = await webSearchApi.getConfig();
      const nextConfig = { ...emptyConfig, ...(response.config || {}) };
      setConfig(nextConfig);
      form.setFieldsValue(nextConfig);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "加载 Web 检索配置失败",
      );
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    void fetchConfig();
  }, [fetchConfig]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const values = await form.validateFields();
      const response = await webSearchApi.updateConfig(values);
      const nextConfig = { ...emptyConfig, ...(response.config || {}) };
      setConfig(nextConfig);
      form.setFieldsValue(nextConfig);
      message.success("公共 Web 检索配置已保存");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const values = await form.validateFields();
      const result = await webSearchApi.testConfig(values);
      const sample = result.sample_title
        ? `，示例：${result.sample_title}`
        : "";
      message.success(
        `连接成功，${result.latency_ms}ms，返回 ${result.result_count} 条${sample}`,
      );
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "IQS 连接测试失败",
      );
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader parent="设置" current="Web 检索" />

      <div className={styles.content}>
        <Alert
          type="info"
          showIcon
          message="平台级公共检索能力"
          description="配置一次后，智能体可使用 web_search 联网搜索和 read_web_page 网页解析；能力不绑定当前模型，也不经过 MCP。"
        />

        <Card
          className={styles.providerCard}
          loading={loading}
          title={
            <div className={styles.providerHeader}>
              <Space size={10} align="start">
                <Globe2 size={21} />
                <div>
                  <h3 className={styles.providerTitle}>阿里云 IQS</h3>
                  <p className={styles.providerDesc}>
                    UnifiedSearch · LiteAdvanced +
                    ReadPageBasic，覆盖搜索与网页深读。
                  </p>
                </div>
              </Space>
              <Space>
                <Tag color={config.configured ? "green" : "default"}>
                  {config.configured ? "已配置" : "未配置"}
                </Tag>
                <Tag color={config.available ? "blue" : "default"}>
                  {config.available ? "可用" : "未启用"}
                </Tag>
              </Space>
            </div>
          }
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={emptyConfig}
            onFinish={handleSave}
          >
            <div className={styles.formGrid}>
              <Form.Item
                name="enabled"
                label="供所有智能体使用"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>

              <Form.Item label="服务状态">
                <Typography.Text
                  type={config.available ? "success" : "secondary"}
                >
                  {config.available
                    ? "Provider 已启用，智能体可调用 web_search"
                    : "保存 API Key 并启用后生效"}
                </Typography.Text>
              </Form.Item>

              <Form.Item
                name="api_key"
                label="IQS API Key"
                rules={[{ required: true, message: "请输入 IQS API Key" }]}
                extra="密钥由服务端加密保存，不会写入智能体配置。"
              >
                <Input.Password
                  placeholder="在阿里云 IQS 控制台创建的 API Key"
                  autoComplete="off"
                />
              </Form.Item>

              <Form.Item name="engine_type" label="搜索引擎">
                <Input disabled addonBefore={<Search size={14} />} />
              </Form.Item>

              <Form.Item name="endpoint" label="Endpoint">
                <Input disabled />
              </Form.Item>

              <Form.Item
                name="default_max_results"
                label="默认返回条数"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} max={10} addonAfter="条" />
              </Form.Item>

              <Form.Item name="timeout_seconds" label="请求超时">
                <InputNumber min={5} max={30} addonAfter="秒" />
              </Form.Item>

              <Form.Item name="cache_ttl_seconds" label="相同检索缓存">
                <InputNumber min={0} max={3600} addonAfter="秒" />
              </Form.Item>
            </div>

            <Alert
              className={styles.billingAlert}
              type="warning"
              showIcon
              message="“测试连接”会向 IQS 发起一次真实检索并产生一次调用费用。"
            />

            <div className={styles.actions}>
              <Button
                icon={<ExternalLink size={15} />}
                href="https://help.aliyun.com/zh/document_detail/2872258.html"
                target="_blank"
              >
                获取 API Key
              </Button>
              <Button
                icon={<Wifi size={15} />}
                loading={testing}
                onClick={handleTest}
              >
                测试连接
              </Button>
              <Button
                type="primary"
                htmlType="submit"
                icon={<Save size={15} />}
                loading={saving}
              >
                保存配置
              </Button>
            </div>
          </Form>
        </Card>
      </div>
    </div>
  );
}
