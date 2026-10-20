import { useCallback, useEffect, useState } from "react";
import {
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Tag,
  Popconfirm,
  Select,
  Card,
} from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { adminUsersApi, type AdminUser } from "../../../api/modules/adminUsers";
import { Headset, KeyRound, Trash2, UserPlus, Users } from "lucide-react";
import { PageHeader } from "../../../components/PageHeader";
import dayjs from "dayjs";
import styles from "./index.module.less";

interface CreateUserFormValues {
  username: string;
  display_name: string;
  phone_number: string;
  password: string;
  role?: "admin" | "user";
  ai_customer_service_url?: string;
}

interface ResetPasswordFormValues {
  new_password: string;
}

interface SceneFormValues {
  ai_customer_service_url?: string;
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function UsersPage() {
  const { message } = useAppMessage();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [resetModalVisible, setResetModalVisible] = useState(false);
  const [sceneModalVisible, setSceneModalVisible] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);

  const [createForm] = Form.useForm();
  const [resetForm] = Form.useForm();
  const [sceneForm] = Form.useForm<SceneFormValues>();

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminUsersApi.listUsers();
      setUsers(data);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "获取用户列表失败"));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleCreateUser = async (values: CreateUserFormValues) => {
    try {
      const input = {
        username: values.username,
        display_name: values.display_name.trim(),
        phone_number: values.phone_number.trim(),
        password: values.password,
        role: values.role || "user",
        ...(values.ai_customer_service_url?.trim()
          ? { ai_customer_service_url: values.ai_customer_service_url.trim() }
          : {}),
      };
      await adminUsersApi.createUser(input);
      message.success("用户创建成功");
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "创建用户失败"));
    }
  };

  const handleSceneUpdate = async (values: SceneFormValues) => {
    if (selectedUserId === null) return;
    try {
      await adminUsersApi.updateAiCustomerServiceUrl(
        selectedUserId,
        values.ai_customer_service_url?.trim() || null,
      );
      message.success("AI 客服入口已更新");
      setSceneModalVisible(false);
      sceneForm.resetFields();
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "更新 AI 客服入口失败"));
    }
  };

  const handleResetPassword = async (values: ResetPasswordFormValues) => {
    if (selectedUserId === null) return;
    try {
      await adminUsersApi.resetPassword(selectedUserId, values.new_password);
      message.success("密码重置成功");
      setResetModalVisible(false);
      resetForm.resetFields();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "密码重置失败"));
    }
  };

  const handleDeleteUser = async (userId: number) => {
    try {
      await adminUsersApi.deleteUser(userId);
      message.success("用户删除成功");
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "删除用户失败"));
    }
  };

  const columns = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 72,
    },
    {
      title: "登录 ID",
      dataIndex: "username",
      key: "username",
      width: 180,
    },
    {
      title: "姓名",
      dataIndex: "display_name",
      key: "display_name",
      width: 160,
      render: (value: string | null) => value || "—",
    },
    {
      title: "手机号",
      dataIndex: "phone_number",
      key: "phone_number",
      width: 180,
      render: (value: string | null) => value || "—",
    },
    {
      title: "角色",
      dataIndex: "role",
      key: "role",
      width: 120,
      render: (role: string) => (
        <Tag color={role === "admin" ? "blue" : "green"}>
          {role === "admin" ? "管理员" : "普通用户"}
        </Tag>
      ),
    },
    {
      title: "AI 客服",
      dataIndex: "ai_customer_service_url",
      key: "ai_customer_service_url",
      width: 120,
      render: (value: string | null) =>
        value ? <Tag color="blue">已开通</Tag> : <Tag>未开通</Tag>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 210,
      render: (val: string) => dayjs(val).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "操作",
      key: "actions",
      width: 340,
      render: (_: unknown, record: AdminUser) => (
        <Space className={styles.actions}>
          <Button
            type="text"
            icon={<Headset size={16} />}
            onClick={() => {
              setSelectedUserId(record.id);
              sceneForm.setFieldsValue({
                ai_customer_service_url:
                  record.ai_customer_service_url || undefined,
              });
              setSceneModalVisible(true);
            }}
          >
            AI客服入口
          </Button>
          <Button
            type="text"
            icon={<KeyRound size={16} />}
            onClick={() => {
              setSelectedUserId(record.id);
              setResetModalVisible(true);
            }}
          >
            重置密码
          </Button>
          <Popconfirm
            title="确定要删除此用户吗？"
            onConfirm={() => handleDeleteUser(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="text" danger icon={<Trash2 size={16} />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        parent="设置"
        current="用户管理"
        extra={
          <Button
            type="primary"
            icon={<UserPlus size={16} />}
            onClick={() => setCreateModalVisible(true)}
          >
            创建用户
          </Button>
        }
      />

      <div className={styles.content}>
        <Card
          className={styles.userCard}
          title={
            <div className={styles.cardTitle}>
              <Users size={18} />
              <span>用户列表</span>
              <span className={styles.cardCount}>{users.length}</span>
            </div>
          }
        >
          <Table
            className={styles.userTable}
            dataSource={users}
            columns={columns}
            rowKey="id"
            loading={loading}
            size="middle"
            scroll={{ x: 1360 }}
            pagination={{ pageSize: 20, showSizeChanger: false }}
          />
        </Card>
      </div>

      <Modal
        title="创建用户"
        width={480}
        open={createModalVisible}
        onCancel={() => {
          setCreateModalVisible(false);
          createForm.resetFields();
        }}
        onOk={() => createForm.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreateUser}>
          <Form.Item
            name="username"
            label="登录 ID"
            rules={[
              { required: true, whitespace: true, message: "请输入登录 ID！" },
            ]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="display_name"
            label="姓名"
            rules={[
              { required: true, whitespace: true, message: "请输入姓名！" },
            ]}
          >
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="phone_number"
            label="手机号"
            rules={[
              { required: true, whitespace: true, message: "请输入手机号！" },
              {
                pattern: /^(?:\+86)?1[3-9]\d{9}$/,
                message: "请输入有效的中国大陆手机号！",
              },
            ]}
          >
            <Input maxLength={14} />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: "请输入密码！" }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="role" label="角色" initialValue="user">
            <Select>
              <Select.Option value="admin">管理员 (admin)</Select.Option>
              <Select.Option value="user">普通用户 (user)</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="ai_customer_service_url"
            label="AI 客服工作区 URL（选填）"
            rules={[
              { type: "url", message: "请输入有效的 URL！" },
              {
                validator: async (_, value) => {
                  if (!value || String(value).trim().startsWith("https://")) {
                    return;
                  }
                  throw new Error("AI 客服入口必须使用 HTTPS！");
                },
              },
            ]}
          >
            <Input placeholder="https://customer-service.example.com/console/?workspace=..." />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="AI 客服入口"
        width={560}
        open={sceneModalVisible}
        onCancel={() => {
          setSceneModalVisible(false);
          sceneForm.resetFields();
        }}
        onOk={() => sceneForm.submit()}
        okText="保存"
        cancelText="取消"
      >
        <Form form={sceneForm} layout="vertical" onFinish={handleSceneUpdate}>
          <Form.Item
            name="ai_customer_service_url"
            label="工作区 URL"
            extra="留空保存将从该账号移除 AI 客服场景 Tab。"
            rules={[
              { type: "url", message: "请输入有效的 URL！" },
              {
                validator: async (_, value) => {
                  if (!value || String(value).trim().startsWith("https://")) {
                    return;
                  }
                  throw new Error("AI 客服入口必须使用 HTTPS！");
                },
              },
            ]}
          >
            <Input placeholder="https://customer-service.example.com/console/?workspace=..." />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="重置密码"
        width={480}
        open={resetModalVisible}
        onCancel={() => {
          setResetModalVisible(false);
          resetForm.resetFields();
        }}
        onOk={() => resetForm.submit()}
        okText="重置"
        cancelText="取消"
      >
        <Form form={resetForm} layout="vertical" onFinish={handleResetPassword}>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[{ required: true, message: "请输入新密码！" }]}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
