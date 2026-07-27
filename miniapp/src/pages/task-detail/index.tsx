import { Button, Text, Textarea, View } from "@tarojs/components";
import Taro, { useDidShow, useRouter } from "@tarojs/taro";
import { useEffect, useMemo, useState } from "react";

import AppShell from "../../components/AppShell";
import ArtifactImage from "../../components/ArtifactImage";
import ConfirmationCard from "../../components/ConfirmationCard";
import OptionPicker, {
  type OptionPickerItem,
} from "../../components/OptionPicker";
import StateView from "../../components/StateView";
import usePageShare from "../../hooks/usePageShare";
import { requireAuth } from "../../services/auth";
import {
  cleanArtifactMessageText,
  hasArtifactTrigger,
  mergeMessageArtifacts,
  messageContentText,
  messageImagePaths,
  shouldRecoverMissingArtifacts,
} from "../../services/artifactTrigger";
import { sendTaskPrompt, stopTask } from "../../services/consoleChat";
import {
  AUTO_MODEL_OPTION,
  getActiveModelId,
  getModelSelectionUnavailableMessage,
  listModelOptions,
  setActiveModel,
  type MobileModelOption,
} from "../../services/modelContext";
import {
  approveConfirmation,
  denyConfirmation,
  getTaskDetail,
  type MobileTaskDetailResponse,
} from "../../services/mobile";
import {
  expertModeOptionIdFor,
  formatTaskPrompt,
  getExpertModeSelectionUnavailableMessage,
  getSkillSelectionUnavailableMessage,
  listAgentOptions,
  listSkillOptions,
  parseExpertModeOptionId,
  TASK_MODE_OPTIONS,
  toExpertModeOptions,
  type MobileAgentOption,
  type MobileTaskMode,
  type MobileSkillOption,
} from "../../services/taskContext";

import "./index.scss";

const FALLBACK_AGENT: MobileAgentOption = {
  id: "default",
  name: "Default",
};

const STATUS_LABELS: Record<
  MobileTaskDetailResponse["task"]["display_status"],
  string
> = {
  running: "执行中",
  pending_confirmation: "待确认",
  completed: "已完成",
  failed: "失败",
  idle: "未开始",
};

const POLL_INTERVAL_MS = 2000;

type PickerType = "expertMode" | "model" | "skill" | "";

function messageRole(message: Record<string, unknown>): string {
  return typeof message.role === "string" ? message.role : "assistant";
}

export default function TaskDetailPage() {
  const router = useRouter();
  const chatId = String(router.params.chatId || "");
  const [detail, setDetail] = useState<MobileTaskDetailResponse | null>(null);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [agentOptions, setAgentOptions] = useState<MobileAgentOption[]>([]);
  const [modelOptions, setModelOptions] = useState<MobileModelOption[]>([
    AUTO_MODEL_OPTION,
  ]);
  const [skillOptions, setSkillOptions] = useState<MobileSkillOption[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("default");
  const [selectedTaskMode, setSelectedTaskMode] =
    useState<MobileTaskMode>("craft");
  const [selectedModelId, setSelectedModelId] = useState(AUTO_MODEL_OPTION.id);
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [pickerType, setPickerType] = useState<PickerType>("");
  const [artifactRecoveryPolls, setArtifactRecoveryPolls] = useState(0);

  usePageShare({
    title: "DClaw｜任务详情",
    path: chatId
      ? `/pages/task-detail/index?chatId=${encodeURIComponent(chatId)}`
      : "/pages/task-detail/index",
  });

  const displayedArtifacts = useMemo(
    () => mergeMessageArtifacts(detail?.messages || [], detail?.artifacts || []),
    [detail?.artifacts, detail?.messages],
  );
  const timelineMessages = useMemo(
    () => {
      const seenImages = new Set<string>();
      return (detail?.messages || [])
        .map((message) => {
          const images = messageImagePaths(message).filter((path) => {
            if (seenImages.has(path)) {
              return false;
            }
            seenImages.add(path);
            return true;
          });
          return {
            role: messageRole(message),
            text: cleanArtifactMessageText(messageContentText(message)),
            images,
          };
        })
        .filter((message) => message.text || message.images.length);
    },
    [detail?.messages],
  );

  const selectedAgent =
    agentOptions.find((agent) => agent.id === selectedAgentId) ||
    (detail?.task.agent_id
      ? {
          id: detail.task.agent_id,
          name: detail.task.agent_id,
        }
      : FALLBACK_AGENT);
  const selectedModel =
    modelOptions.find((model) => model.id === selectedModelId) ||
    AUTO_MODEL_OPTION;
  const selectedSkill =
    skillOptions.find((skill) => skill.id === selectedSkillId) || null;
  const selectedTaskModeOption = TASK_MODE_OPTIONS.find(
    (option) => option.mode === selectedTaskMode,
  );
  const selectedExpertModeName = selectedTaskModeOption?.name || selectedAgent.name;
  const expertModePickerOptions = toExpertModeOptions(agentOptions);
  const selectedExpertModeId = expertModeOptionIdFor(
    selectedTaskMode,
    selectedAgent.id,
  );
  const modelPickerOptions = modelOptions.length
    ? modelOptions
    : [AUTO_MODEL_OPTION];
  const skillPickerOptions: OptionPickerItem[] = [
    {
      id: "",
      name: "不使用技能",
      description: "直接交给当前专家 / 模式处理",
    },
    ...skillOptions,
  ];

  const loadAgentDependentOptions = async (agentId: string) => {
    const [models, activeModelId, skills] = await Promise.all([
      listModelOptions().catch(() => [AUTO_MODEL_OPTION]),
      getActiveModelId({ agentId, chatId }).catch(() => AUTO_MODEL_OPTION.id),
      listSkillOptions(agentId),
    ]);
    setModelOptions(models);
    setSelectedModelId(
      models.some((model) => model.id === activeModelId)
        ? activeModelId
        : AUTO_MODEL_OPTION.id,
    );
    setSkillOptions(skills);
  };

  const loadContextOptions = async (agentId: string) => {
    try {
      const agents = await listAgentOptions();
      const nextAgentId =
        agents.find((agent) => agent.id === agentId)?.id ||
        agents.find((agent) => agent.id === FALLBACK_AGENT.id)?.id ||
        agents[0]?.id ||
        agentId ||
        FALLBACK_AGENT.id;
      setAgentOptions(agents.length ? agents : [FALLBACK_AGENT]);
      setSelectedAgentId(nextAgentId);
      await loadAgentDependentOptions(nextAgentId);
    } catch (error) {
      setAgentOptions([FALLBACK_AGENT]);
      setSelectedAgentId(agentId || FALLBACK_AGENT.id);
      setModelOptions([AUTO_MODEL_OPTION]);
      setSelectedModelId(AUTO_MODEL_OPTION.id);
      setSkillOptions([]);
    }
  };

  const loadDetail = async (options: { silent?: boolean } = {}) => {
    if (!requireAuth()) {
      return;
    }
    if (!chatId) {
      setErrorMessage("缺少任务参数，无法打开详情");
      return;
    }
    if (!options.silent) {
      setLoading(true);
      setErrorMessage("");
    }
    try {
      const response = await getTaskDetail(chatId);
      setDetail(response);
      const needsArtifactRecovery =
        response.artifacts.length === 0 && hasArtifactTrigger(response.messages);
      setArtifactRecoveryPolls((current) => {
        if (!needsArtifactRecovery) {
          return 0;
        }
        return options.silent ? current + 1 : 0;
      });
      if (!options.silent) {
        const taskMode = response.task.active_mode;
        setSelectedTaskMode(
          taskMode === "plan" || taskMode === "ask" || taskMode === ""
            ? taskMode
            : "craft",
        );
        await loadContextOptions(response.task.agent_id || selectedAgentId);
      }
    } catch (error) {
      if (!options.silent) {
        setErrorMessage(error instanceof Error ? error.message : "加载失败");
      }
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  };

  useDidShow(() => {
    loadDetail();
  });

  useEffect(() => {
    if (!chatId) {
      return undefined;
    }
    const shouldPoll =
      !detail ||
      detail.messages.length === 0 ||
      detail.task.display_status === "running" ||
      detail.task.display_status === "pending_confirmation" ||
      shouldRecoverMissingArtifacts({
        messages: detail.messages,
        artifactCount: detail.artifacts.length,
        recoveryPolls: artifactRecoveryPolls,
      });
    if (!shouldPoll) {
      return undefined;
    }
    const timer = setInterval(() => {
      void loadDetail({ silent: true });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [
    artifactRecoveryPolls,
    chatId,
    detail?.artifacts.length,
    detail?.messages,
    detail?.task.display_status,
  ]);

  const submitPrompt = async () => {
    if (!detail || !prompt.trim()) {
      return;
    }
    try {
      const formattedPrompt = formatTaskPrompt(
        prompt,
        selectedSkill,
        selectedTaskMode,
      );
      await sendTaskPrompt({
        chatId: detail.task.id,
        sessionId: detail.task.session_id,
        prompt: formattedPrompt,
        agentId: selectedAgent.id,
        activeMode: selectedTaskMode,
        skillName: selectedSkill?.id,
        expertTeamId: detail.task.expert_team_id || undefined,
      });
      setPrompt("");
      setSelectedSkillId("");
      await loadDetail();
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "发送失败",
        icon: "none",
      });
    }
  };

  const chooseExpertMode = async () => {
    let options = agentOptions.length ? agentOptions : [FALLBACK_AGENT];
    if (options.length <= 1) {
      try {
        const refreshed = await listAgentOptions();
        if (refreshed.length) {
          options = refreshed;
          setAgentOptions(refreshed);
        }
      } catch {
        // Keep the current options and show a clear unavailable message below.
      }
    }
    const unavailableMessage = getExpertModeSelectionUnavailableMessage(options);
    if (unavailableMessage) {
      Taro.showToast({ title: unavailableMessage, icon: "none" });
      return;
    }
    setPickerType("expertMode");
  };

  const chooseModel = async () => {
    let options = modelPickerOptions;
    if (options.length <= 1) {
      Taro.showLoading({ title: "刷新模型中" });
      try {
        options = await listModelOptions();
        setModelOptions(options);
      } finally {
        Taro.hideLoading();
      }
    }
    const unavailableMessage = getModelSelectionUnavailableMessage(options);
    if (unavailableMessage) {
      Taro.showToast({ title: unavailableMessage, icon: "none" });
      return;
    }
    setPickerType("model");
  };

  const chooseSkill = async () => {
    let options = skillOptions;
    if (!options.length) {
      Taro.showLoading({ title: "刷新技能中" });
      try {
        options = await listSkillOptions(selectedAgent.id);
        setSkillOptions(options);
      } finally {
        Taro.hideLoading();
      }
    }
    const unavailableMessage = getSkillSelectionUnavailableMessage(options);
    if (unavailableMessage) {
      Taro.showToast({ title: unavailableMessage, icon: "none" });
      return;
    }
    setPickerType("skill");
  };

  const selectExpertMode = async (optionId: string) => {
    const selection = parseExpertModeOptionId(optionId);
    if (selection.mode) {
      setPickerType("");
      setSelectedTaskMode(selection.mode);
      setSelectedAgentId(FALLBACK_AGENT.id);
      setSelectedModelId(AUTO_MODEL_OPTION.id);
      setSelectedSkillId("");
      await loadAgentDependentOptions(FALLBACK_AGENT.id);
      return;
    }
    const agentId = selection.agentId || "";
    const nextAgent = agentOptions.find((agent) => agent.id === agentId);
    if (!nextAgent) {
      return;
    }
    setPickerType("");
    setSelectedTaskMode("");
    setSelectedAgentId(nextAgent.id);
    setSelectedModelId(AUTO_MODEL_OPTION.id);
    setSelectedSkillId("");
    await loadAgentDependentOptions(nextAgent.id);
  };

  const selectModel = async (modelId: string) => {
    setPickerType("");
    try {
      await setActiveModel({
        modelId,
        agentId: selectedAgent.id,
        chatId: detail?.task.id || chatId,
      });
      setSelectedModelId(modelId);
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "模型切换失败",
        icon: "none",
      });
    }
  };

  const selectSkill = (skillId: string) => {
    setPickerType("");
    setSelectedSkillId(skillId);
  };

  const handleStop = async () => {
    if (!detail) {
      return;
    }
    try {
      await stopTask(detail.task.id);
      await loadDetail();
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "停止失败",
        icon: "none",
      });
    }
  };

  const handleApprove = async (requestId: string) => {
    try {
      await approveConfirmation(requestId);
      await loadDetail();
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "确认失败",
        icon: "none",
      });
    }
  };

  const handleDeny = async (requestId: string) => {
    try {
      await denyConfirmation(requestId);
      await loadDetail();
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "拒绝失败",
        icon: "none",
      });
    }
  };

  return (
    <AppShell className="task-detail-page">
      <Text className="page-title">任务详情</Text>
      {detail ? (
        <>
          <View className="card task-summary">
            <Text className="task-title">{detail.task.name}</Text>
            <Text className="task-status">
              状态：{STATUS_LABELS[detail.task.display_status]}
            </Text>
            {!!displayedArtifacts.length && (
              <Text
                className="result-link"
                onClick={() =>
                  Taro.navigateTo({
                    url: `/pages/result/index?chatId=${detail.task.id}`,
                  })
                }
              >
                查看产物文件
              </Text>
            )}
          </View>

          {detail.confirmations.map((confirmation) => (
            <ConfirmationCard
              key={confirmation.request_id}
              confirmation={confirmation}
              onApprove={handleApprove}
              onDeny={handleDeny}
            />
          ))}

          {!!displayedArtifacts.length && (
            <View className="card artifact-card">
              <View className="artifact-card__header">
                <Text className="card-title">任务产物</Text>
                <Text
                  className="result-link"
                  onClick={() =>
                    Taro.navigateTo({
                      url: `/pages/result/index?chatId=${detail.task.id}`,
                    })
                  }
                >
                  查看全部
                </Text>
              </View>
              {displayedArtifacts.slice(0, 3).map((artifact) => (
                <View
                  key={artifact.path}
                  className="artifact-row"
                  onClick={() =>
                    Taro.navigateTo({
                      url: `/pages/result/index?chatId=${detail.task.id}`,
                    })
                  }
                >
                  {artifact.kind === "image" && (
                    <ArtifactImage
                      chatId={detail.task.id}
                      path={artifact.path}
                      className="artifact-row__preview"
                    />
                  )}
                  <Text className="artifact-row__name">{artifact.name}</Text>
                  <Text className="artifact-row__kind">{artifact.kind}</Text>
                </View>
              ))}
            </View>
          )}

          <View className="card timeline-card">
            <Text className="card-title">消息时间线</Text>
            {timelineMessages.length ? (
              <View className="message-list">
                {timelineMessages.map((message, index) => {
                  const role = message.role;
                  return (
                    <View
                      key={`${role}-${index}`}
                      className={`message-bubble message-bubble--${role}`}
                    >
                      <Text className="message-role">
                        {role === "user" ? "我" : "DClaw"}
                      </Text>
                      {!!message.text && (
                        <Text className="message-text">{message.text}</Text>
                      )}
                      {!!message.images.length && (
                        <View className="message-images">
                          {message.images.map((path) => (
                            <ArtifactImage
                              key={path}
                              chatId={detail.task.id}
                              path={path}
                              className="message-image"
                            />
                          ))}
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            ) : (
              <Text className="muted-text">等待任务消息同步</Text>
            )}
          </View>

          <View className="composer">
            <View className="composer-toolbar">
              <View className="composer-chip" onClick={chooseExpertMode}>
                <Text className="composer-chip__label">专家 / 模式</Text>
                <Text className="composer-chip__value">
                  {selectedExpertModeName}
                </Text>
              </View>
              <View className="composer-chip" onClick={chooseModel}>
                <Text className="composer-chip__label">模型</Text>
                <Text className="composer-chip__value">
                  {selectedModel.name}
                </Text>
              </View>
              <View className="composer-chip" onClick={chooseSkill}>
                <Text className="composer-chip__label">技能</Text>
                <Text className="composer-chip__value">
                  {selectedSkill?.name || "不使用技能"}
                </Text>
              </View>
            </View>
            <Textarea
              className="composer-input"
              value={prompt}
              placeholder="输入你的需求..."
              onInput={(event) => setPrompt(String(event.detail.value || ""))}
            />
            <View className="composer-actions">
              <Button className="secondary-button" onClick={handleStop}>
                停止
              </Button>
              <Button className="primary-button" onClick={submitPrompt}>
                发送
              </Button>
            </View>
          </View>
        </>
      ) : loading ? (
        <StateView
          type="loading"
          title="正在打开任务"
          description="DClaw 正在同步任务进度和消息"
        />
      ) : errorMessage ? (
        <StateView
          type="error"
          title="任务详情加载失败"
          description={errorMessage}
          actionText={chatId ? "重新加载" : undefined}
          onAction={chatId ? loadDetail : undefined}
        />
      ) : (
        <StateView
          type="empty"
          title="没有找到任务"
          description="请从任务列表重新打开"
        />
      )}
      <OptionPicker
        open={pickerType === "expertMode"}
        title="选择专家 / 模式"
        options={expertModePickerOptions}
        selectedId={selectedExpertModeId}
        emptyText="暂无可选专家 / 模式"
        onClose={() => setPickerType("")}
        onSelect={selectExpertMode}
      />
      <OptionPicker
        open={pickerType === "model"}
        title="选择模型"
        options={modelPickerOptions}
        selectedId={selectedModel.id}
        emptyText="暂无可选模型"
        onClose={() => setPickerType("")}
        onSelect={selectModel}
      />
      <OptionPicker
        open={pickerType === "skill"}
        title="选择技能"
        options={skillPickerOptions}
        selectedId={selectedSkill?.id || ""}
        emptyText="暂无可选技能"
        onClose={() => setPickerType("")}
        onSelect={selectSkill}
      />
    </AppShell>
  );
}
