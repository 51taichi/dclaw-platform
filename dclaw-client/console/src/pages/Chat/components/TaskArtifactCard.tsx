import React from "react";
import { FileCode, FileDown, CheckSquare, Globe } from "lucide-react";
import { useAgentStore } from "../../../stores/agentStore";
import { filterUserTaskFiles } from "../utils/artifactFilters";
import { buildWorkspacePreviewUrl } from "./previewUrl";
import styles from "./TaskArtifactCard.module.less";

interface TaskArtifactCardProps {
  chatId: string;
  files: string[];
}

export const TaskArtifactCard: React.FC<TaskArtifactCardProps> = ({
  chatId,
  files,
}) => {
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const [previewImage, setPreviewImage] = React.useState<{
    url: string;
    alt: string;
  } | null>(null);
  const workflowFiles = ["task.md", "implementation_plan.md"];
  const filteredFiles = filterUserTaskFiles(files);

  // Artifacts (Clean deliverables)
  const artifactFiles = filteredFiles.filter((f) => !workflowFiles.includes(f));
  const isImageArtifact = (filename: string) => {
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    return ["png", "jpg", "jpeg", "webp", "gif", "bmp", "svg"].includes(ext);
  };
  const imageFiles = artifactFiles.filter(isImageArtifact);
  const nonImageArtifactFiles = artifactFiles.filter(
    (file) => !isImageArtifact(file),
  );

  // Include task.md as "Tasks" in the deliverables list if it exists
  const hasTasks = filteredFiles.includes("task.md");

  // Check if there is any HTML page to preview
  const htmlFile = filteredFiles.find((f) => {
    const ext = f.split(".").pop()?.toLowerCase() || "";
    return ["html", "htm"].includes(ext);
  });

  const getFileIcon = (filename: string) => {
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    if (
      [
        "html",
        "htm",
        "ts",
        "tsx",
        "js",
        "jsx",
        "py",
        "go",
        "rs",
        "json",
        "sh",
      ].includes(ext)
    ) {
      return <FileCode size={13} className={styles.iconHtml} />;
    }
    return <FileDown size={13} className={styles.iconText} />;
  };

  const handleFileClick = (
    path: string,
    activeTab: "artifacts" | "changes" | "browser" | "files",
  ) => {
    window.dispatchEvent(
      new CustomEvent("preview-artifact", {
        detail: { path, activeTab, chatId },
      }),
    );
  };

  const handleViewAllArtifacts = () => {
    window.dispatchEvent(
      new CustomEvent("preview-artifact", {
        detail: { path: "task.md", activeTab: "products", chatId },
      }),
    );
  };

  const handleWebPreview = () => {
    if (htmlFile) {
      window.dispatchEvent(
        new CustomEvent("preview-artifact", {
          detail: { path: htmlFile, activeTab: "browser", chatId },
        }),
      );
    }
  };

  const getImagePreviewUrl = (path: string) =>
    buildWorkspacePreviewUrl({
      path,
      agentId: selectedAgent,
      chatId,
    });

  if (files.length === 0) return null;

  if (artifactFiles.length === 0 && !hasTasks) {
    return (
      <div className={styles.container}>
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            本次任务没有生成独立文件，结果已在对话中展示。
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {imageFiles.length > 0 && (
        <div className={styles.conversationImageStrip}>
          {imageFiles.map((file, index) => {
            const url = getImagePreviewUrl(file);
            const alt = `对话图片 ${index + 1}`;
            return (
              <button
                key={file}
                type="button"
                className={styles.conversationImagePreview}
                onClick={() => setPreviewImage({ url, alt })}
                title="点击查看大图"
              >
                <img src={url} alt={alt} />
              </button>
            );
          })}
        </div>
      )}

      {/* 1. Deliverables (任务产生制品) */}
      {(artifactFiles.length > 0 || hasTasks) && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            任务产生制品（{artifactFiles.length + (hasTasks ? 1 : 0)}个）：
          </div>

          {imageFiles.length > 0 && (
            <div className={styles.imageGrid}>
              {imageFiles.map((file) => (
                <button
                  key={file}
                  type="button"
                  className={styles.imageThumb}
                  onClick={() => handleFileClick(file, "artifacts")}
                  title={file}
                >
                  <img src={getImagePreviewUrl(file)} alt={file} />
                  <span>{file.split("/").pop() || file}</span>
                </button>
              ))}
            </div>
          )}

          <div className={styles.tagList}>
            {nonImageArtifactFiles.map((file) => {
              const ext = file.split(".").pop()?.toLowerCase() || "";
              const isHtml = ["html", "htm"].includes(ext);
              return (
                <div
                  key={file}
                  className={styles.tagItem}
                  onClick={() =>
                    handleFileClick(file, isHtml ? "browser" : "artifacts")
                  }
                >
                  {getFileIcon(file)}
                  <span className={styles.tagName}>{file}</span>
                </div>
              );
            })}

            {hasTasks && (
              <div
                className={styles.tagItem}
                onClick={() => handleFileClick("task.md", "artifacts")}
              >
                <CheckSquare size={13} className={styles.iconTasks} />
                <span className={styles.tagName}>Tasks</span>
              </div>
            )}

            <span className={styles.blueLink} onClick={handleViewAllArtifacts}>
              查看全部制品 →
            </span>
          </div>
        </div>
      )}

      {/* 2. Open Web Preview Button (打开网页预览) */}
      {htmlFile && (
        <div className={styles.buttonContainer}>
          <div className={styles.webPreviewBtn} onClick={handleWebPreview}>
            <Globe size={14} />
            <span>打开网页预览 →</span>
          </div>
        </div>
      )}

      {previewImage && (
        <div
          className={styles.imageDialogBackdrop}
          onClick={() => setPreviewImage(null)}
        >
          <div
            className={styles.imageDialog}
            role="dialog"
            aria-label="图片预览"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className={styles.imageDialogClose}
              onClick={() => setPreviewImage(null)}
            >
              关闭
            </button>
            <img src={previewImage.url} alt="图片预览" />
          </div>
        </div>
      )}
    </div>
  );
};
