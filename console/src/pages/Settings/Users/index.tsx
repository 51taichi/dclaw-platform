import { useEffect, useState } from "react";
import { Table, Button, Space, Modal, Form, Input, Tag, Popconfirm, Select } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { adminUsersApi, AdminUser } from "../../../api/modules/adminUsers";
import { SparkSearchUserLine, SparkDeleteLine, SparkModifyLine } from "@agentscope-ai/icons";
import dayjs from "dayjs";

export default function UsersPage() {
  const { message } = useAppMessage();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [resetModalVisible, setResetModalVisible] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);

  const [createForm] = Form.useForm();
  const [resetForm] = Form.useForm();

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const data = await adminUsersApi.listUsers();
      setUsers(data);
    } catch (err: any) {
      message.error(err.message || "获取用户列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleCreateUser = async (values: any) => {
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
    } catch (err: any) {
      message.error(err.message || "创建用户失败");
    }
  };

  const handleResetPassword = async (values: any) => {
    if (selectedUserId === null) return;
    try {
      await adminUsersApi.resetPassword(selectedUserId, values.new_password);
      message.success("密码重置成功");
      setResetModalVisible(false);
      resetForm.resetFields();
    } catch (err: any) {
      message.error(err.message || "密码重置失败");
    }
  };

  const handleDeleteUser = async (userId: number) => {
    try {
      await adminUsersApi.deleteUser(userId);
      message.success("用户删除成功");
      fetchUsers();
    } catch (err: any) {
      message.error(err.message || "删除用户失败");
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'blue' : 'green'}>{role === 'admin' ? '管理员' : '普通用户'}</Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => dayjs(val).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: AdminUser) => (
        <Space>
          <Button
            type="text"
            icon={<SparkModifyLine size={16} />}
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
            <Button type="text" danger icon={<SparkDeleteLine size={16} />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2>用户管理</h2>
        <Button
          type="primary"
          icon={<SparkSearchUserLine size={16} />}
          onClick={() => setCreateModalVisible(true)}
        >
          创建用户
        </Button>
      </div>

      <Table
        dataSource={users}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title="创建用户"
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
            rules={[{ required: true, message: '请输入用户名！' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码！' }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="role"
            label="角色"
            initialValue="user"
          >
            <Select>
              <Select.Option value="admin">管理员 (admin)</Select.Option>
              <Select.Option value="user">普通用户 (user)</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="重置密码"
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
            rules={[{ required: true, message: '请输入新密码！' }]}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
