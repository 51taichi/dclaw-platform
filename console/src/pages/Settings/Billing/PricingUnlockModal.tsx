import { useState } from "react";
import { Form, Input, Modal } from "antd";
import { billingApi } from "../../../api/modules/billing";
import type { PricingUnlock } from "../../../api/types/billing";

export default function PricingUnlockModal({
  open,
  onCancel,
  onUnlocked,
}: {
  open: boolean;
  onCancel: () => void;
  onUnlocked: (value: PricingUnlock) => void;
}) {
  const [form] = Form.useForm<{ password: string }>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const submit = async () => {
    const { password } = await form.validateFields();
    setLoading(true);
    setError(undefined);
    try {
      const result = await billingApi.unlockPricing(password);
      form.resetFields();
      onUnlocked(result);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setLoading(false);
    }
  };
  return (
    <Modal
      open={open}
      title="解锁计费设置"
      okText="确认解锁"
      cancelText="取消"
      confirmLoading={loading}
      onOk={() => void submit()}
      onCancel={() => {
        form.resetFields();
        setError(undefined);
        onCancel();
      }}
    >
      <p>请输入当前管理员密码。解锁仅对计费设置有效，15分钟后自动失效。</p>
      <Form form={form} layout="vertical">
        <Form.Item
          label="管理员密码"
          name="password"
          validateStatus={error ? "error" : undefined}
          help={error}
          rules={[{ required: true, message: "请输入管理员密码" }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
