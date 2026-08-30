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
import { KeyRound, Trash2, UserPlus, Users } from "lucide-react";
import { PageHeader } from "../../../components/PageHeader";
import dayjs from "dayjs";
import styles from "./index.module.less";

interface CreateUserFormValues {
  username: string;
  password: string;
  role?: "admin" | "user";
}

interface ResetPasswordFormValues {
  new_password: string;
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
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);

  const [createForm] = Form.useForm();
  const [resetForm] = Form.useForm();

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
      await adminUsersApi.createUser({
        username: values.username,
        password: values.password,
        role: values.role || "user",
      });
      message.success("用户创建成功");
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "创建用户失败"));
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
      title: "用户名",
      dataIndex: "username",
      key: "username",
      width: 180,
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
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 210,
      render: (val: string) => dayjs(val).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "操作",
      key: "actions",
      width: 220,
      render: (_: unknown, record: AdminUser) => (
        <Space className={styles.actions}>
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
            scroll={{ x: 800 }}
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
            label="用户名"
            rules={[{ required: true, message: "请输入用户名！" }]}
          >
            <Input />
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
