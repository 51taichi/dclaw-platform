import { useAgentsData, FileListPanel, FileEditor } from "./components";
import styles from "./index.module.less";
import { UploadOutlined, DownloadOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "@agentscope-ai/design";
import { workspaceApi } from "../../../api/modules/workspace";
import { saveDownloadedBlob } from "../../../utils/download";
import { useRef, useEffect, useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { Select } from "antd";
import { useAgentStore } from "../../../stores/agentStore";
import { agentsApi } from "../../../api/modules/agents";

export default function WorkspacePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent, setSelectedAgent, agents, setAgents } =
    useAgentStore();
  const [loadingAgents, setLoadingAgents] = useState(false);

  useEffect(() => {
    if (agents.length === 0) {
      setLoadingAgents(true);
      agentsApi
        .listAgents()
        .then((res) => {
          if (res && res.agents) {
            setAgents(res.agents);
          }
        })
        .catch((err) => {
          console.error("Failed to load agents in workspace page:", err);
        })
        .finally(() => {
          setLoadingAgents(false);
        });
    }
  }, [agents.length, setAgents]);

  const agentOptions = useMemo(() => {
    const list = [...agents];
    if (!list.some((a) => a.id === "default")) {
      list.unshift({
        id: "default",
        name: t("agent.defaultAgentName", "默认智能体"),
        description: "",
        workspace_dir: "~/.qwenpaw/workspaces/default",
      } as any);
    }
    return list.map((a) => ({
      value: a.id,
      label: a.name || a.id,
    }));
  }, [agents, t]);

  const {
    files,
    selectedFile,
    dailyMemories,
    expandedMemory,
    fileContent,
    loading,
    workspacePath,
    hasChanges,
    enabledFiles,
    setFileContent,
    fetchFiles,
    handleFileClick,
    handleDailyMemoryClick,
    handleSave,
    handleReset,
    handleToggleFileEnabled,
    handleReorderFiles,
  } = useAgentsData();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDownload = async () => {
    try {
      const { blob, filename } = await workspaceApi.downloadWorkspace();
      if (await saveDownloadedBlob(blob, filename)) {
        message.success(t("workspace.downloadSuccess"));
      }
    } catch (error) {
      console.error("Download failed:", error);
      message.error(
        t("workspace.downloadFailed") + ": " + (error as Error).message,
      );
    }
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Check if file is zip format
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.error(t("workspace.zipOnly"));
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    const maxSizeMb = 100;
    const maxSize = maxSizeMb * 1024 * 1024;
    if (file.size > maxSize) {
      message.error(
        t("workspace.fileSizeExceeded", {
          limit: maxSizeMb,
          size: (file.size / (1024 * 1024)).toFixed(2),
        }),
      );
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    try {
      const result = await workspaceApi.uploadFile(file);
      if (result.success) {
        message.success(t("workspace.uploadSuccess"));
      } else {
        message.error(t("workspace.uploadFailed") + ": " + result.message);
      }
    } catch (error) {
      console.error("Upload failed:", error);
      message.error(
        t("workspace.uploadFailed") + ": " + (error as Error).message,
      );
    } finally {
      // Clear input value to allow re-uploading the same file
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className={styles.workspacePage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("workspace.title") }]}
        afterBreadcrumb={
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              marginLeft: 16,
            }}
          >
            <Select
              showSearch
              value={selectedAgent}
              onChange={(value) => {
                setSelectedAgent(value);
              }}
              loading={loadingAgents}
              className={styles.agentSelect}
              options={agentOptions}
              optionFilterProp="label"
              filterOption={(input, option) =>
                (option?.label ?? "")
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
              placeholder={t("workspace.selectAgent", "选择智能体")}
            />
            <p className={styles.workspacePath} style={{ margin: 0 }}>
              {t("workspace.workspacePath")}{" "}
              {workspacePath === null
                ? t("common.loading")
                : workspacePath || t("workspace.noFiles")}
            </p>
          </div>
        }
        extra={
          <div className={styles.workspaceInfo}>
            <div className={styles.actionButtons}>
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                style={{ display: "none" }}
                accept=".zip"
                title="Select a ZIP file (max 100MB)"
              />
              <Tooltip
                title={t("workspace.uploadTooltip")}
                placement="top"
                mouseEnterDelay={0.5}
              >
                <Button
                  size="small"
                  onClick={handleUploadClick}
                  icon={<UploadOutlined />}
                >
                  {t("common.upload")}
                </Button>
              </Tooltip>
              <Button
                size="small"
                onClick={handleDownload}
                icon={<DownloadOutlined />}
              >
                {t("common.download")}
              </Button>
            </div>
          </div>
        }
      />

      <div className={styles.content}>
        <FileListPanel
          files={files}
          selectedFile={selectedFile}
          dailyMemories={dailyMemories}
          expandedMemory={expandedMemory}
          workspacePath={workspacePath}
          enabledFiles={enabledFiles}
          onRefresh={fetchFiles}
          onFileClick={handleFileClick}
          onDailyMemoryClick={handleDailyMemoryClick}
          onToggleEnabled={handleToggleFileEnabled}
          onReorder={handleReorderFiles}
        />

        <FileEditor
          selectedFile={selectedFile}
          fileContent={fileContent}
          loading={loading}
          hasChanges={hasChanges}
          onContentChange={setFileContent}
          onSave={handleSave}
          onReset={handleReset}
        />
      </div>
    </div>
  );
}
