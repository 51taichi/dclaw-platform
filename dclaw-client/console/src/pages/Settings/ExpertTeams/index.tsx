import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Drawer,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { Plus } from "lucide-react";
import { PageHeader } from "../../../components/PageHeader";
import { expertTeamsApi } from "../../../api/modules/expertTeams";
import type { ExpertTeamTemplate } from "../../../api/types/expertTeams";

const EMPTY_TEAM: Partial<ExpertTeamTemplate> = {
  name: "新专家团",
  description: "",
  category: "content",
  icon: "👥",
  enabled: true,
  leader_agent_id: "default",
  tags: [],
  members: [],
  workflow: [],
  source: "custom",
  sort_order: 100,
};

export default function ExpertTeamsAdminPage() {
  const [teams, setTeams] = useState<ExpertTeamTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ExpertTeamTemplate | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const loadTeams = async () => {
    setLoading(true);
    try {
      setTeams(await expertTeamsApi.listAdminExpertTeams());
    } catch {
      message.error("获取专家团失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTeams();
  }, []);

  const openEditor = (team?: ExpertTeamTemplate) => {
    const value = team || EMPTY_TEAM;
    setEditing((team as ExpertTeamTemplate) || null);
    setDraft(JSON.stringify(value, null, 2));
  };

  const saveDraft = async () => {
    let payload: Partial<ExpertTeamTemplate>;
    try {
      payload = JSON.parse(draft);
    } catch {
      message.error("JSON 格式不正确");
      return;
    }

    setSaving(true);
    try {
      if (editing?.id) {
        await expertTeamsApi.updateAdminExpertTeam(editing.id, payload);
      } else {
        await expertTeamsApi.createAdminExpertTeam(payload);
      }
      message.success("已保存专家团");
      setEditing(null);
      setDraft("");
      await loadTeams();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const columns = useMemo<ColumnsType<ExpertTeamTemplate>>(
    () => [
      {
        title: "专家团",
        dataIndex: "name",
        render: (_, team) => (
          <Space direction="vertical" size={2}>
            <Space>
              <span>{team.icon || "👥"}</span>
              <strong>{team.name}</strong>
              <Tag>{team.source === "builtin" ? "内置" : "自定义"}</Tag>
            </Space>
            <span style={{ color: "#8c8c8c", fontSize: 12 }}>
              {team.description || team.id}
            </span>
          </Space>
        ),
      },
      {
        title: "分类",
        dataIndex: "category",
        width: 120,
      },
      {
        title: "成员",
        dataIndex: "members",
        width: 120,
        render: (members) => `${members?.length || 0} 位`,
      },
      {
        title: "使用",
        dataIndex: "usage_count",
        width: 100,
      },
      {
        title: "启用",
        dataIndex: "enabled",
        width: 100,
        render: (enabled, team) => (
          <Switch
            checked={enabled}
            onChange={async (checked) => {
              await expertTeamsApi.updateAdminExpertTeam(team.id, {
                enabled: checked,
              });
              await loadTeams();
            }}
          />
        ),
      },
      {
        title: "操作",
        width: 160,
        render: (_, team) => (
          <Space>
            <Button size="small" onClick={() => openEditor(team)}>
              编辑
            </Button>
            {team.source !== "builtin" && (
              <Button
                size="small"
                danger
                onClick={() => {
                  Modal.confirm({
                    title: `删除「${team.name}」？`,
                    okText: "删除",
                    okButtonProps: { danger: true },
                    cancelText: "取消",
                    onOk: async () => {
                      await expertTeamsApi.deleteAdminExpertTeam(team.id);
                      await loadTeams();
                    },
                  });
                }}
              >
                删除
              </Button>
            )}
          </Space>
        ),
      },
    ],
    [],
  );

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        parent="设置"
        current="专家团"
        extra={
          <Button
            type="primary"
            icon={<Plus size={14} />}
            onClick={() => openEditor()}
          >
            创建专家团
          </Button>
        }
      />
      <section aria-label="专家团列表" style={{ marginTop: 16 }}>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={teams}
          pagination={false}
        />
      </section>

      <Drawer
        title={editing ? `编辑 ${editing.name}` : "创建专家团"}
        open={!!draft}
        onClose={() => {
          setEditing(null);
          setDraft("");
        }}
        width={720}
        extra={
          <Button type="primary" loading={saving} onClick={saveDraft}>
            保存
          </Button>
        }
      >
        <Input.TextArea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          autoSize={{ minRows: 24 }}
          style={{ fontFamily: "Menlo, Consolas, monospace", fontSize: 12 }}
        />
      </Drawer>
    </div>
  );
}
