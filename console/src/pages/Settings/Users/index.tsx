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
  Tabs,
} from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  adminUsersApi,
  type AdminUser,
  type SceneTabInput,
} from "../../../api/modules/adminUsers";
import {
  KeyRound,
  PanelsTopLeft,
  Plus,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { PageHeader } from "../../../components/PageHeader";
import dayjs from "dayjs";
import styles from "./index.module.less";
import {
  DEFAULT_SCENE_ICON,
  SCENE_ICON_OPTIONS,
  normalizeSceneIcon,
} from "../../../features/scenes/sceneIconConfig";
import { SceneIcon } from "../../../features/scenes/sceneIcons";

interface CreateUserFormValues {
  username: string;
  display_name: string;
  phone_number: string;
  password: string;
  role?: "admin" | "user";
  scene_tabs?: SceneTabInput[];
}

interface ResetPasswordFormValues {
  new_password: string;
}

interface SceneFormValues {
  scene_tabs?: SceneTabInput[];
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function normalizeSceneTabs(sceneTabs: SceneTabInput[] | undefined) {
  return (sceneTabs || []).map((scene) => ({
    title: scene.title.trim(),
    url: scene.url.trim(),
    icon: normalizeSceneIcon(scene.icon),
  }));
}

function getUserSceneTabs(user: AdminUser): SceneTabInput[] {
  if (Array.isArray(user.scene_tabs)) {
    return user.scene_tabs.map((scene) => ({
      ...scene,
      icon: normalizeSceneIcon(scene.icon),
    }));
  }
  return user.ai_customer_service_url
    ? [
        {
          title: "AI客服",
          url: user.ai_customer_service_url,
          icon: DEFAULT_SCENE_ICON,
        },
      ]
    : [];
}

function SceneTabsFields() {
  return (
    <Form.List name="scene_tabs">
      {(fields, { add, remove }) => (
        <div className={styles.sceneEditor}>
          <div className={styles.sceneEditorHeader}>
            <div className={styles.sceneEditorTitle}>外链场景 Tab</div>
            <Button
              type="dashed"
              icon={<Plus size={15} />}
              onClick={() =>
                add({ title: "", url: "", icon: DEFAULT_SCENE_ICON })
              }
            >
              添加 Tab
            </Button>
          </div>
          {fields.map(({ key, name, ...field }, index) => (
            <div className={styles.sceneRow} key={key}>
              <Form.Item {...field} name={[name, "icon"]} label="图标">
                <Select
                  virtual={false}
                  options={SCENE_ICON_OPTIONS.map((option) => ({
                    value: option.value,
                    label: (
                      <span className={styles.sceneIconLabel}>
                        <SceneIcon name={option.value} />
                        <span>{option.label}</span>
                      </span>
                    ),
                  }))}
                />
              </Form.Item>
              <Form.Item
                {...field}
                name={[name, "title"]}
                label={`Tab ${index + 1} 名称`}
                rules={[
                  {
                    required: true,
                    whitespace: true,
                    message: "请输入 Tab 名称！",
                  },
                  { max: 40, message: "Tab 名称不能超过 40 个字符！" },
                ]}
              >
                <Input placeholder="例如：AI客服" maxLength={40} />
              </Form.Item>
              <Form.Item
                {...field}
                name={[name, "url"]}
                label="HTTPS URL"
                rules={[
                  { required: true, whitespace: true, message: "请输入 URL！" },
                  { type: "url", message: "请输入有效的 URL！" },
                  {
                    validator: async (_, value) => {
                      if (
                        String(value || "")
                          .trim()
                          .startsWith("https://")
                      ) {
                        return;
                      }
                      throw new Error("外链必须使用 HTTPS！");
                    },
                  },
                ]}
              >
                <Input placeholder="https://example.com/workspace/..." />
              </Form.Item>
              <Button
                className={styles.removeSceneButton}
                type="text"
                danger
                icon={<Trash2 size={16} />}
                aria-label={`删除 Tab ${index + 1}`}
                onClick={() => remove(name)}
              />
            </div>
          ))}
        </div>
      )}
    </Form.List>
  );
}

export default function UsersPage() {
  const { message } = useAppMessage();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [resetModalVisible, setResetModalVisible] = useState(false);
  const [sceneModalVisible, setSceneModalVisible] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [createTabKey, setCreateTabKey] = useState("account");

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
        scene_tabs: normalizeSceneTabs(values.scene_tabs),
      };
      await adminUsersApi.createUser(input);
      message.success("用户创建成功");
      setCreateModalVisible(false);
      setCreateTabKey("account");
      createForm.resetFields();
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "创建用户失败"));
    }
  };

  const handleSceneUpdate = async (values: SceneFormValues) => {
    if (selectedUserId === null) return;
    try {
      await adminUsersApi.updateSceneTabs(
        selectedUserId,
        normalizeSceneTabs(values.scene_tabs),
      );
      message.success("场景 Tab 已更新");
      setSceneModalVisible(false);
      sceneForm.resetFields();
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "更新场景 Tab 失败"));
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
      title: "场景 Tab",
      key: "scene_tabs",
      width: 120,
      render: (_: unknown, record: AdminUser) => {
        const count = getUserSceneTabs(record).length;
        return count ? (
          <Tag color="blue">{count} 个 Tab</Tag>
        ) : (
          <Tag>未配置</Tag>
        );
      },
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
            icon={<PanelsTopLeft size={16} />}
            onClick={() => {
              setSelectedUserId(record.id);
              sceneForm.setFieldsValue({
                scene_tabs: getUserSceneTabs(record),
              });
              setSceneModalVisible(true);
            }}
          >
            编辑场景 Tab
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
            onClick={() => {
              setCreateTabKey("account");
              setCreateModalVisible(true);
            }}
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
        width={920}
        open={createModalVisible}
        onCancel={() => {
          setCreateModalVisible(false);
          setCreateTabKey("account");
          createForm.resetFields();
        }}
        onOk={() => createForm.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreateUser}
          onFinishFailed={({ errorFields }) => {
            const hasAccountError = errorFields.some(
              ({ name }) => name[0] !== "scene_tabs",
            );
            setCreateTabKey(hasAccountError ? "account" : "scenes");
          }}
        >
          <Tabs
            activeKey={createTabKey}
            onChange={setCreateTabKey}
            items={[
              {
                key: "account",
                label: "基本信息",
                children: (
                  <div
                    className={`${styles.createTabContent} ${styles.accountFieldsGrid}`}
                  >
                    <Form.Item
                      name="username"
                      label="登录 ID"
                      rules={[
                        {
                          required: true,
                          whitespace: true,
                          message: "请输入登录 ID！",
                        },
                      ]}
                    >
                      <Input />
                    </Form.Item>
                    <Form.Item name="role" label="角色" initialValue="user">
                      <Select>
                        <Select.Option value="admin">
                          管理员 (admin)
                        </Select.Option>
                        <Select.Option value="user">
                          普通用户 (user)
                        </Select.Option>
                      </Select>
                    </Form.Item>
                    <Form.Item
                      name="display_name"
                      label="姓名"
                      rules={[
                        {
                          required: true,
                          whitespace: true,
                          message: "请输入姓名！",
                        },
                      ]}
                    >
                      <Input maxLength={100} />
                    </Form.Item>
                    <Form.Item
                      name="phone_number"
                      label="手机号"
                      rules={[
                        {
                          required: true,
                          whitespace: true,
                          message: "请输入手机号！",
                        },
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
                      label="初始密码"
                      rules={[{ required: true, message: "请输入密码！" }]}
                    >
                      <Input.Password />
                    </Form.Item>
                  </div>
                ),
              },
              {
                key: "scenes",
                label: "外链 Tab（选填）",
                children: (
                  <div className={styles.createTabContent}>
                    <SceneTabsFields />
                  </div>
                ),
              },
            ]}
          />
        </Form>
      </Modal>

      <Modal
        title="编辑场景 Tab"
        width={920}
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
          <SceneTabsFields />
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
