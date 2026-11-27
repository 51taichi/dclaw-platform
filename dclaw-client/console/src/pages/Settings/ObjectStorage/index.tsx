import { useEffect, useState } from "react";
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
  message,
} from "antd";
import { CloudUpload, Save, Wifi } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { request } from "../../../api";
import styles from "./index.module.less";

interface ObjectStorageConfig {
  provider: "aliyun_oss";
  enabled: boolean;
  endpoint: string;
  bucket: string;
  access_key_id: string;
  access_key_secret: string;
  prefix: string;
  signed_url_ttl_seconds: number;
  configured: boolean;
  updated_at?: string;
}

const emptyConfig: ObjectStorageConfig = {
  provider: "aliyun_oss",
  enabled: false,
  endpoint: "",
  bucket: "",
  access_key_id: "",
  access_key_secret: "",
  prefix: "aigc/generated",
  signed_url_ttl_seconds: 900,
  configured: false,
};

export default function ObjectStoragePage() {
  const [form] = Form.useForm<ObjectStorageConfig>();
  const [config, setConfig] = useState<ObjectStorageConfig>(emptyConfig);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await request<{ config: ObjectStorageConfig }>(
        "/admin/object-storage/config",
      );
      const nextConfig = { ...emptyConfig, ...(res.config || {}) };
      setConfig(nextConfig);
      form.setFieldsValue(nextConfig);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载对象存储配置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchConfig();
  }, []);

  const currentPayload = () => ({
    ...emptyConfig,
    ...config,
    ...form.getFieldsValue(true),
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      const values = currentPayload();
      const res = await request<{ config: ObjectStorageConfig }>(
        "/admin/object-storage/config",
        {
          method: "PUT",
          body: JSON.stringify(values),
        },
      );
      const nextConfig = { ...emptyConfig, ...(res.config || {}) };
      setConfig(nextConfig);
      form.setFieldsValue(nextConfig);
      message.success("对象存储配置已保存");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const values = currentPayload();
      const res = await request<{
        ok: boolean;
        bucket: string;
        object_key: string;
      }>("/admin/object-storage/test", {
        method: "POST",
        body: JSON.stringify(values),
      });
      message.success(`连接成功：${res.bucket}/${res.object_key}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "测试连接失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader parent="设置" current="对象存储" />

      <div className={styles.content}>
        <Alert
          type="info"
          showIcon
          message="启用后，新生成的 AIGC 图片、视频和文件会写入阿里云 OSS；ECS 仅保存元数据和访问入口。"
        />

        <Card
          className={styles.providerCard}
          loading={loading}
          title={
            <div className={styles.providerHeader}>
              <Space size={10}>
                <CloudUpload size={20} />
                <div>
                  <h3 className={styles.providerTitle}>阿里云 OSS</h3>
                  <p className={styles.providerDesc}>
                    建议使用私有 Bucket，系统会在访问时生成短期签名 URL。
                  </p>
                </div>
              </Space>
              <Tag color={config.configured ? "green" : "default"}>
                {config.configured ? "已配置" : "未配置"}
              </Tag>
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
              <Form.Item name="enabled" label="启用" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item name="signed_url_ttl_seconds" label="签名 URL 有效期">
                <InputNumber min={60} max={604800} addonAfter="秒" />
              </Form.Item>

              <Form.Item name="endpoint" label="Endpoint">
                <Input placeholder="https://oss-cn-hangzhou.aliyuncs.com" />
              </Form.Item>

              <Form.Item name="bucket" label="Bucket">
                <Input placeholder="qwenpaw-aigc" />
              </Form.Item>

              <Form.Item name="access_key_id" label="Access Key ID">
                <Input placeholder="RAM 用户 AccessKey ID" />
              </Form.Item>

              <Form.Item name="access_key_secret" label="Access Key Secret">
                <Input.Password placeholder="留空或保持 ******** 则保留已有密钥" />
              </Form.Item>

              <Form.Item name="prefix" label="对象前缀" className={styles.full}>
                <Input placeholder="aigc/generated" />
              </Form.Item>
            </div>

            <div className={styles.actions}>
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
