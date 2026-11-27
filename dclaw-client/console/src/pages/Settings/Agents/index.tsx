import {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
  type ChangeEvent,
} from "react";
import { Card, Button, Form, Modal } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PlusOutlined, TeamOutlined, UploadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "../../../api/modules/agents";
import { invalidateSkillCache, skillApi } from "../../../api/modules/skill";
import type { AgentSummary } from "../../../api/types/agents";
import type { ProviderInfo } from "../../../api/types/provider";
import { providerApi } from "../../../api/modules/provider";
import { useAgentStore } from "../../../stores/agentStore";
import { useAgents } from "./useAgents";
import { AgentTable, AgentModal } from "./components";
import { PageHeader } from "@/components/PageHeader";
import { reorderAgents } from "./reorder";
import { isChatSelectableModel } from "../../Chat/utils/chatModelEligibility";
import styles from "./index.module.less";

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function AgentsPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { agents, loading, deleteAgent, toggleAgent, loadAgents, setAgents } =
    useAgents();
  const { selectedAgent, setSelectedAgent } = useAgentStore();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [reordering, setReordering] = useState(false);
  const [importingPackage, setImportingPackage] = useState(false);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [savingModelAgentId, setSavingModelAgentId] = useState<string | null>(
    null,
  );
  const [form] = Form.useForm();
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const installedSkillsRef = useRef<string[]>([]);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const { message } = useAppMessage();

  useEffect(() => {
    providerApi
      .listProviders()
      .then((data) => setProviders(Array.isArray(data) ? data : []))
      .catch((error) => {
        console.error("Failed to load model options:", error);
        message.error(t("agent.modelLoadFailed"));
      });
  }, [message, t]);

  const modelOptions = useMemo(
    () =>
      providers.flatMap((provider) => {
        const configured =
          provider.require_api_key === false
            ? !!provider.base_url
            : provider.is_custom
            ? !!provider.base_url
            : !!provider.api_key;
        if (!configured) return [];
        return [...(provider.models ?? []), ...(provider.extra_models ?? [])]
          .filter(isChatSelectableModel)
          .map((model) => ({
            label: `${provider.name} / ${model.name || model.id}`,
            value: `${provider.id}\u0000${model.id}`,
          }));
      }),
    [providers],
  );

  const handleCreate = () => {
    setEditingAgent(null);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
      active_model_provider: undefined,
      active_model_model: undefined,
    });
    setSelectedSkills([]);
    installedSkillsRef.current = [];
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    try {
      setSelectedSkills([]);
      installedSkillsRef.current = [];
      invalidateSkillCache({ agentId: agent.id });
      const config = await agentsApi.getAgent(agent.id);
      setEditingAgent(agent);
      form.setFieldsValue({
        ...config,
        active_model_provider: config.active_model?.provider_id || undefined,
        active_model_model: config.active_model?.model || undefined,
      });
      setModalVisible(true);
    } catch (error) {
      console.error("Failed to load agent config:", error);
      message.error(t("agent.loadConfigFailed"));
    }
  };

  const handleDelete = async (agentId: string) => {
    try {
      await deleteAgent(agentId);

      if (selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      message.error(t("agent.deleteFailed"));
    }
  };

  const handleToggle = async (agentId: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    try {
      await toggleAgent(agentId, newEnabled);

      if (!newEnabled && selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      // Error already handled in hook
    }
  };

  const handleModelChange = async (
    agentId: string,
    model: { provider_id: string; model: string } | null,
  ) => {
    setSavingModelAgentId(agentId);
    try {
      if (model) {
        await providerApi.setActiveLlm({
          ...model,
          scope: "agent",
          agent_id: agentId,
        });
      } else {
        await providerApi.deleteActiveLlm({
          scope: "agent",
          agent_id: agentId,
        });
      }
      setAgents(
        agents.map((agent) =>
          agent.id === agentId ? { ...agent, active_model: model } : agent,
        ),
      );
      message.success(
        model ? t("agent.modelUpdateSuccess") : t("agent.modelClearSuccess"),
      );
    } catch (error) {
      console.error("Failed to update agent model:", error);
      message.error(t("agent.modelUpdateFailed"));
    } finally {
      setSavingModelAgentId(null);
    }
  };

  const handleInstalledSkillsLoaded = useCallback((skills: string[]) => {
    installedSkillsRef.current = skills;
  }, []);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const workspaceRaw = values.workspace_dir;
      const workspace_dir =
        typeof workspaceRaw === "string"
          ? workspaceRaw.trim() || undefined
          : workspaceRaw;

      const providerId = values.active_model_provider;
      const modelId = values.active_model_model;
      const active_model =
        providerId && modelId
          ? { provider_id: providerId, model: modelId }
          : null;

      const payload = { ...values, workspace_dir, active_model };
      delete payload.active_model_provider;
      delete payload.active_model_model;

      if (editingAgent) {
        const previousInstalledSkills = installedSkillsRef.current;
        const newSkills = selectedSkills.filter(
          (skill) => !previousInstalledSkills.includes(skill),
        );

        for (const skill of newSkills) {
          await skillApi.downloadSkillPoolSkill({
            skill_name: skill,
            targets: [{ workspace_id: editingAgent.id }],
          });
        }
        await agentsApi.updateAgent(editingAgent.id, payload);
        installedSkillsRef.current = [
          ...previousInstalledSkills,
          ...newSkills.filter(
            (skill) => !previousInstalledSkills.includes(skill),
          ),
        ];
        invalidateSkillCache({ agentId: editingAgent.id });
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent({
          ...payload,
          language: i18n.language,
          skill_names: selectedSkills,
        });
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      setModalVisible(false);
      await loadAgents();
    } catch (error: unknown) {
      console.error("Failed to save agent:", error);
      if (editingAgent) {
        invalidateSkillCache({ agentId: editingAgent.id });
      }
      message.error(getErrorMessage(error, t("agent.saveFailed")));
    }
  };

  const handleReorder = async (activeId: string, overId: string) => {
    const nextAgents = reorderAgents(agents, activeId, overId);
    if (nextAgents === agents) {
      return;
    }

    const previousAgents = agents;
    setAgents(nextAgents);
    setReordering(true);

    try {
      await agentsApi.reorderAgents(nextAgents.map((agent) => agent.id));
      message.success(t("agent.reorderSuccess"));
    } catch (error) {
      console.error("Failed to reorder agents:", error);
      setAgents(previousAgents);
      message.error(t("agent.reorderFailed"));
    } finally {
      setReordering(false);
    }
  };

  const handleImportPackageFile = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.error("请选择 zip 格式的 Agent 包");
      return;
    }

    setImportingPackage(true);
    try {
      const preview = await agentsApi.previewAgentPackage(file);
      const finalAgentId = preview.id;
      const willUpdateExisting = preview.has_conflict;
      const skillLabel =
        preview.skills.length > 0
          ? preview.skills.slice(0, 6).join("、") +
            (preview.skills.length > 6 ? " ..." : "")
          : "未发现技能";
      const actionLabel = willUpdateExisting
        ? "更新现有 Agent"
        : "创建新 Agent";

      setImportingPackage(false);
      Modal.confirm({
        title: "导入 Agent 包",
        okText: willUpdateExisting ? "确认更新" : "确认导入",
        cancelText: "取消",
        width: 560,
        content: (
          <div className={styles.importPreview}>
            <div className={styles.importPreviewGrid}>
              <span>包内名称</span>
              <strong>{preview.name}</strong>
              <span>包内 ID</span>
              <strong>{preview.id}</strong>
              <span>导入 ID</span>
              <strong>{finalAgentId}</strong>
              <span>导入方式</span>
              <strong>{actionLabel}</strong>
              <span>识别根目录</span>
              <strong>{preview.root_path}</strong>
              <span>文件数量</span>
              <strong>{preview.files_count}</strong>
              <span>技能</span>
              <strong>{skillLabel}</strong>
            </div>
            {preview.warnings.length > 0 && (
              <div className={styles.importWarnings}>
                {preview.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            )}
          </div>
        ),
        onOk: async () => {
          setImportingPackage(true);
          try {
            const result = await agentsApi.importAgentPackage(file, {
              agent_id: finalAgentId,
              enabled: true,
              mode: willUpdateExisting ? "update" : "create",
            });
            message.success(
              `${willUpdateExisting ? "更新" : "导入"}成功：${
                result.name
              } (ID: ${result.agent_id})`,
            );
            await loadAgents();
          } catch (error: unknown) {
            console.error("Failed to import agent package:", error);
            message.error(getErrorMessage(error, "导入 Agent 包失败"));
            throw error;
          } finally {
            setImportingPackage(false);
          }
        },
      });
    } catch (error: unknown) {
      console.error("Failed to preview agent package:", error);
      setImportingPackage(false);
      message.error(getErrorMessage(error, "解析 Agent 包失败"));
    }
  };

  return (
    <div className={styles.agentsPage}>
      <input
        ref={importInputRef}
        type="file"
        hidden
        accept=".zip,application/zip,application/x-zip-compressed"
        onChange={handleImportPackageFile}
      />
      <PageHeader
        parent={t("agent.parent")}
        current={t("agent.agents")}
        extra={
          <div className={styles.headerRight}>
            <Button
              type="default"
              icon={<TeamOutlined />}
              onClick={() => navigate("/admin/expert-teams")}
            >
              管理专家团
            </Button>
            <Button
              type="default"
              icon={<UploadOutlined />}
              loading={importingPackage}
              disabled={importingPackage}
              onClick={() => importInputRef.current?.click()}
            >
              导入 Agent 包
            </Button>
            <Button
              type="default"
              icon={<PlusOutlined />}
              onClick={handleCreate}
            >
              {t("agent.create")}
            </Button>
          </div>
        }
      />

      <Card className={styles.tableCard}>
        <AgentTable
          agents={agents}
          loading={loading || reordering}
          reordering={reordering}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onToggle={handleToggle}
          onReorder={handleReorder}
          modelOptions={modelOptions}
          savingModelAgentId={savingModelAgentId}
          onModelChange={handleModelChange}
        />
      </Card>

      <AgentModal
        open={modalVisible}
        editingAgent={editingAgent}
        form={form}
        selectedSkills={selectedSkills}
        onSelectedSkillsChange={setSelectedSkills}
        onInstalledSkillsLoaded={handleInstalledSkillsLoaded}
        onSave={handleSubmit}
        onCancel={() => setModalVisible(false)}
      />
    </div>
  );
}
