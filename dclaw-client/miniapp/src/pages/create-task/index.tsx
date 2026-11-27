import { Button, Text, Textarea, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import AssetImage from "../../components/AssetImage";
import OptionPicker, {
  type OptionPickerItem,
} from "../../components/OptionPicker";
import usePageShare from "../../hooks/usePageShare";
import {
  uploadConsoleAttachment,
  type UploadedAttachment,
} from "../../services/attachments";
import { requireAuth } from "../../services/auth";
import { createAndSubmitTask } from "../../services/consoleChat";
import {
  AUTO_MODEL_OPTION,
  getActiveModelId,
  getModelSelectionUnavailableMessage,
  listModelOptions,
  setActiveModel,
  type MobileModelOption,
} from "../../services/modelContext";
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

const TASK_TEMPLATES = [
  "整理上周项目进展",
  "生成销售数据分析摘要",
  "结合企业知识库和个人知识库，整理这个问题的背景、结论和可执行建议",
  "把资料整理成汇报提纲",
];

const AIGC_WEB_URL = "https://dclaw.deepmega.cn/";

type SelectedLocalFile = {
  path?: string;
  name?: string;
  tempFilePath?: string;
};

type PickerType = "expertMode" | "model" | "skill" | "";
type TaskEntryType = "chat" | "aigc";

export default function CreateTaskPage() {
  usePageShare({
    title: "用 DClaw 发起 AI 任务",
    path: "/pages/create-task/index",
  });

  const [selectedEntryType, setSelectedEntryType] =
    useState<TaskEntryType>("chat");
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [agentOptions, setAgentOptions] = useState<MobileAgentOption[]>([]);
  const [modelOptions, setModelOptions] = useState<MobileModelOption[]>([
    AUTO_MODEL_OPTION,
  ]);
  const [skillOptions, setSkillOptions] = useState<MobileSkillOption[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState(FALLBACK_AGENT.id);
  const [selectedTaskMode, setSelectedTaskMode] =
    useState<MobileTaskMode>("craft");
  const [selectedModelId, setSelectedModelId] = useState(AUTO_MODEL_OPTION.id);
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [attachments, setAttachments] = useState<UploadedAttachment[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [pickerType, setPickerType] = useState<PickerType>("");

  const selectedAgent =
    agentOptions.find((agent) => agent.id === selectedAgentId) || FALLBACK_AGENT;
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
      getActiveModelId({ agentId }).catch(() => AUTO_MODEL_OPTION.id),
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

  const loadContextOptions = async (agentId = selectedAgentId) => {
    try {
      const agents = await listAgentOptions();
      const nextAgentId =
        agents.find((agent) => agent.id === agentId)?.id ||
        agents.find((agent) => agent.id === FALLBACK_AGENT.id)?.id ||
        agents[0]?.id ||
        FALLBACK_AGENT.id;
      setAgentOptions(agents.length ? agents : [FALLBACK_AGENT]);
      setSelectedAgentId(nextAgentId);
      await loadAgentDependentOptions(nextAgentId);
    } catch {
      setAgentOptions([FALLBACK_AGENT]);
      setSelectedAgentId(FALLBACK_AGENT.id);
      setModelOptions([AUTO_MODEL_OPTION]);
      setSelectedModelId(AUTO_MODEL_OPTION.id);
      setSkillOptions([]);
    }
  };

  useDidShow(() => {
    if (requireAuth()) {
      void loadContextOptions();
    }
  });

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

  const uploadSelectedFiles = async (files: SelectedLocalFile[]) => {
    if (!files.length) {
      return;
    }
    setUploadingAttachment(true);
    try {
      const uploaded: UploadedAttachment[] = [];
      for (const file of files) {
        const path = file.path || file.tempFilePath || "";
        const name = file.name || path.split("/").pop() || "附件";
        if (!path) {
          continue;
        }
        uploaded.push(await uploadConsoleAttachment({ path, name }));
      }
      setAttachments((prev) => [...prev, ...uploaded]);
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "附件上传失败",
        icon: "none",
      });
    } finally {
      setUploadingAttachment(false);
    }
  };

  const chooseMaterial = async () => {
    try {
      const { tapIndex } = await Taro.showActionSheet({
        itemList: ["选择文件", "选择图片"],
      });
      if (tapIndex === 0) {
        const result = await Taro.chooseMessageFile({
          count: 3,
          type: "file",
        });
        await uploadSelectedFiles(result.tempFiles || []);
        return;
      }
      const result = await Taro.chooseMedia({
        count: 3,
        mediaType: ["image"],
      });
      await uploadSelectedFiles(result.tempFiles || []);
    } catch {
      // User cancelled file or media selection.
    }
  };

  const openAigcWebGuide = () => {
    Taro.showModal({
      title: "请到 Web 版体验",
      content: `AIGC 创意项目当前仅支持 PC Web 端。\n体验请到 Web 版：${AIGC_WEB_URL}`,
      confirmText: "复制链接",
      cancelText: "我知道了",
      success: (result) => {
        if (result.confirm) {
          Taro.setClipboardData({ data: AIGC_WEB_URL });
        }
      },
    });
  };

  const selectEntryType = (entryType: TaskEntryType) => {
    setSelectedEntryType(entryType);
    if (entryType === "aigc") {
      openAigcWebGuide();
    }
  };

  const taskNameFrom = (goal: string) => {
    if (goal.trim()) {
      return goal.trim().slice(0, 18);
    }
    return attachments[0]?.name || "新任务";
  };

  const submit = async () => {
    if (!requireAuth()) {
      return;
    }

    const normalizedPrompt = prompt.trim();
    if (!normalizedPrompt && attachments.length === 0) {
      Taro.showToast({ title: "请输入任务目标", icon: "none" });
      return;
    }
    if (uploadingAttachment) {
      Taro.showToast({ title: "附件还在上传中，请稍候", icon: "none" });
      return;
    }

    const attachmentText = attachments.map((item) => item.markdown).join("\n");
    const taskPrompt = [normalizedPrompt, attachmentText]
      .filter(Boolean)
      .join("\n\n");
    const formattedPrompt = formatTaskPrompt(
      taskPrompt,
      selectedSkill,
      selectedTaskMode,
    );

    setSubmitting(true);
    try {
      await createAndSubmitTask({
        name: taskNameFrom(normalizedPrompt),
        prompt: formattedPrompt,
        agentId: selectedAgent.id,
        activeMode: selectedTaskMode,
        skillName: selectedSkill?.id,
      });
      Taro.showToast({ title: "任务已交给 DClaw", icon: "success" });
      Taro.redirectTo({ url: "/pages/tasks/index" });
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "任务发起失败，请稍后重试",
        icon: "none",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell className="create-task-page">
      <Text className="page-title">发起任务</Text>
      <View className="task-type-switch">
        <View
          className={`task-type-tab ${
            selectedEntryType === "chat" ? "task-type-tab--active" : ""
          }`}
          onClick={() => selectEntryType("chat")}
        >
          <Text className="task-type-tab__title">对话任务</Text>
          <Text className="task-type-tab__desc">交给 DClaw 执行</Text>
        </View>
        <View
          className={`task-type-tab ${
            selectedEntryType === "aigc" ? "task-type-tab--active" : ""
          }`}
          onClick={() => selectEntryType("aigc")}
        >
          <Text className="task-type-tab__title">AIGC 创意项目</Text>
          <Text className="task-type-tab__desc">PC Web 体验</Text>
        </View>
      </View>

      {selectedEntryType === "chat" ? (
        <View className="chat-task-content">
          <View className="create-hero">
            <View className="create-hero__copy">
              <Text className="create-hero__title">把工作交给 DClaw</Text>
              <Text className="create-hero__desc">
                选好处理方式和材料，DClaw 会把进展同步到任务里
              </Text>
            </View>
            <AssetImage slot="mascotTask" className="create-hero__mascot" />
          </View>
          <View className="card context-card">
            <Text className="card-title">选择专家 / 模型 / 技能</Text>
            <View className="option-row" onClick={chooseExpertMode}>
              <View className="option-row__body">
                <Text className="option-row__label">专家 / 模式</Text>
                <Text className="option-row__value">
                  {selectedExpertModeName}
                </Text>
              </View>
              <Text className="option-row__action">选择</Text>
            </View>
            <View className="option-row" onClick={chooseModel}>
              <View className="option-row__body">
                <Text className="option-row__label">模型</Text>
                <Text className="option-row__value">{selectedModel.name}</Text>
              </View>
              <Text className="option-row__action">
                {modelPickerOptions.length > 1 ? "选择" : "当前"}
              </Text>
            </View>
            <View className="option-row" onClick={chooseSkill}>
              <View className="option-row__body">
                <Text className="option-row__label">技能</Text>
                <Text className="option-row__value">
                  {selectedSkill?.name || "不使用技能"}
                </Text>
              </View>
              <Text className="option-row__action">
                {skillOptions.length ? "选择" : "暂无"}
              </Text>
            </View>
          </View>

          <View className="card material-card">
            <View className="section-heading">
              <Text className="card-title">补充材料</Text>
              <Text className="section-action" onClick={chooseMaterial}>
                {uploadingAttachment ? "上传中" : "添加"}
              </Text>
            </View>
            {attachments.length ? (
              <View className="attachment-list">
                {attachments.map((item) => (
                  <View
                    key={`${item.name}-${item.url}`}
                    className="attachment-item"
                  >
                    <Text className="attachment-name">{item.name}</Text>
                  </View>
                ))}
              </View>
            ) : (
              <Text className="muted-text">
                可添加文件或图片，让 DClaw 带着材料执行
              </Text>
            )}
          </View>

          <View className="card goal-card">
            <Text className="card-title">描述任务目标</Text>
            <Textarea
              className="prompt-input"
              value={prompt}
              placeholder="告诉 DClaw 要完成什么、参考什么、希望输出什么结果..."
              maxlength={2000}
              onInput={(event) => setPrompt(String(event.detail.value || ""))}
            />
          </View>

          <View className="template-list">
            <Text className="template-title">常用任务</Text>
            {TASK_TEMPLATES.map((template) => (
              <View
                key={template}
                className="template-chip"
                onClick={() => setPrompt(template)}
              >
                <Text>{template}</Text>
              </View>
            ))}
          </View>

          <Button className="submit-button" loading={submitting} onClick={submit}>
            交给 DClaw 执行
          </Button>
        </View>
      ) : (
        <View className="aigc-guide-content">
          <View className="card aigc-guide-card" onClick={openAigcWebGuide}>
            <View className="aigc-guide-card__copy">
              <Text className="card-title">AIGC 创意项目</Text>
              <Text className="muted-text">
                图片、视频、创意画布请到 PC Web 版体验
              </Text>
            </View>
            <AssetImage slot="mascotTask" className="aigc-guide-card__mascot" />
          </View>
          <Button
            className="submit-button aigc-guide-button"
            onClick={openAigcWebGuide}
          >
            查看 Web 版提示
          </Button>
        </View>
      )}

      {selectedEntryType === "aigc" && (
        <View className="aigc-guide-note">
          <Text className="muted-text">体验请到 Web 版：{AIGC_WEB_URL}</Text>
        </View>
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
