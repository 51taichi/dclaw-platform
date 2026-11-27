import { Text, View } from "@tarojs/components";
import Taro, { useDidShow, useRouter } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import ArtifactImage from "../../components/ArtifactImage";
import AssetImage from "../../components/AssetImage";
import StateView from "../../components/StateView";
import usePageShare from "../../hooks/usePageShare";
import { requireAuth } from "../../services/auth";
import {
  filterVisibleArtifacts,
  mergeMessageArtifacts,
} from "../../services/artifactTrigger";
import {
  downloadArtifactFile,
  getResults,
  getTaskDetail,
  saveArtifactImageToAlbum,
  type MobileArtifactSummary,
} from "../../services/mobile";

import "./index.scss";

const IMAGE_EXTENSIONS = new Set([
  "apng",
  "avif",
  "bmp",
  "gif",
  "jpeg",
  "jpg",
  "png",
  "webp",
]);
const DOCUMENT_EXTENSIONS = new Set([
  "doc",
  "docx",
  "pdf",
  "ppt",
  "pptx",
  "xls",
  "xlsx",
]);

function artifactExtension(file: MobileArtifactSummary): string {
  const source = file.path || file.name || "";
  const parts = source.split(".");
  return parts.length > 1 ? String(parts.pop() || "").toLowerCase() : "";
}

function isImageArtifact(file: MobileArtifactSummary): boolean {
  return file.kind === "image" || IMAGE_EXTENSIONS.has(artifactExtension(file));
}

function isDocumentArtifact(file: MobileArtifactSummary): boolean {
  return (
    file.kind === "document" ||
    DOCUMENT_EXTENSIONS.has(artifactExtension(file))
  );
}

function formatFileSize(size?: number | null): string {
  if (!size) {
    return "";
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function albumSaveErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "errMsg" in error) {
    return String((error as { errMsg?: unknown }).errMsg || "");
  }
  return error instanceof Error ? error.message : "";
}

function isAlbumPermissionError(error: unknown): boolean {
  return /auth deny|authorize|permission|scope\.writePhotosAlbum/i.test(
    albumSaveErrorMessage(error),
  );
}

export default function ResultPage() {
  const router = useRouter();
  const chatId = String(router.params.chatId || "");
  const [files, setFiles] = useState<MobileArtifactSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [openingPath, setOpeningPath] = useState("");
  const [savingImagePath, setSavingImagePath] = useState("");

  usePageShare({
    title: "DClaw｜任务结果",
    path: chatId
      ? `/pages/result/index?chatId=${encodeURIComponent(chatId)}`
      : "/pages/result/index",
  });

  const loadResults = async () => {
    if (!requireAuth()) {
      return;
    }
    if (!chatId) {
      setErrorMessage("缺少任务参数，无法读取产物");
      return;
    }
    setLoading(true);
    setErrorMessage("");
    try {
      const artifacts = await getResults(chatId);
      const visibleArtifacts = filterVisibleArtifacts(artifacts);
      if (visibleArtifacts.length) {
        setFiles(visibleArtifacts);
      } else {
        const detail = await getTaskDetail(chatId);
        setFiles(mergeMessageArtifacts(detail.messages, detail.artifacts));
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useDidShow(() => {
    void loadResults();
  });

  const openArtifact = async (file: MobileArtifactSummary) => {
    if (!chatId) {
      return;
    }
    if (isDocumentArtifact(file)) {
      const guide = await Taro.showModal({
        title: "打开文件",
        content: "需要转发或另存时，可打开文件后使用右上角菜单。",
        confirmText: "继续打开",
        cancelText: "取消",
      });
      if (!guide.confirm) {
        return;
      }
    }
    setOpeningPath(file.path);
    try {
      const tempFilePath = await downloadArtifactFile(chatId, file.path);
      if (isImageArtifact(file)) {
        await Taro.previewImage({
          current: tempFilePath,
          urls: [tempFilePath],
        });
        return;
      }
      if (isDocumentArtifact(file)) {
        await Taro.openDocument({
          filePath: tempFilePath,
          showMenu: true,
        });
        return;
      }
      Taro.showModal({
        title: "文件已下载",
        content: "该类型暂不支持在小程序内直接预览，可到 Web 版查看完整产物。",
        confirmText: "复制路径",
        cancelText: "知道了",
        success: (result) => {
          if (result.confirm) {
            Taro.setClipboardData({ data: file.path });
          }
        },
      });
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "打开文件失败",
        icon: "none",
      });
    } finally {
      setOpeningPath("");
    }
  };

  const saveImageToAlbum = async (file: MobileArtifactSummary) => {
    if (!chatId || savingImagePath) {
      return;
    }
    setSavingImagePath(file.path);
    try {
      await saveArtifactImageToAlbum(chatId, file.path);
      Taro.showToast({ title: "已保存到手机相册", icon: "success" });
    } catch (error) {
      if (isAlbumPermissionError(error)) {
        const result = await Taro.showModal({
          title: "需要相册权限",
          content: "请在微信设置中允许保存图片到相册。",
          confirmText: "去设置",
          cancelText: "取消",
        });
        if (result.confirm) {
          await Taro.openSetting();
        }
      } else {
        Taro.showToast({
          title: albumSaveErrorMessage(error) || "保存到相册失败",
          icon: "none",
        });
      }
    } finally {
      setSavingImagePath("");
    }
  };

  return (
    <AppShell className="result-page">
      <Text className="page-title">结果详情</Text>
      <View className="result-hero">
        <View className="result-hero__copy">
          <Text className="result-hero__title">任务产物已归档</Text>
          <Text className="result-hero__desc">文档、表格和分析结果会集中展示</Text>
        </View>
        <AssetImage slot="mascotResult" className="result-hero__mascot" />
      </View>
      <View className="file-list">
        {loading && files.length === 0 && (
          <StateView
            type="loading"
            title="正在读取产物文件"
            description="生成的文档、表格和分析结果会显示在这里"
          />
        )}
        {!!errorMessage && files.length === 0 && (
          <StateView
            type="error"
            title="结果加载失败"
            description={errorMessage}
            actionText={chatId ? "重新加载" : undefined}
            onAction={chatId ? loadResults : undefined}
          />
        )}
        {!loading &&
          files.map((file) => (
            <View
              key={file.path}
              className={`card file-card file-card--${file.kind || "file"}`}
              onClick={() => openArtifact(file)}
            >
              {isImageArtifact(file) ? (
                <ArtifactImage
                  chatId={chatId}
                  path={file.path}
                  className="file-preview"
                />
              ) : (
                <View className="file-icon" />
              )}
              <View className="file-body">
                <Text className="file-title">{file.name}</Text>
                {file.path !== file.name && (
                  <Text className="file-path">{file.path}</Text>
                )}
                <Text className="file-meta">
                  {[file.kind, formatFileSize(file.size)]
                    .filter(Boolean)
                    .join(" · ")}
                </Text>
              </View>
              {isImageArtifact(file) ? (
                <View className="file-actions">
                  <Text
                    className="file-action"
                    onClick={(event) => {
                      event.stopPropagation();
                      void openArtifact(file);
                    }}
                  >
                    {openingPath === file.path ? "打开中" : "预览图片"}
                  </Text>
                  <Text
                    className="file-action file-action--save-image"
                    onClick={(event) => {
                      event.stopPropagation();
                      void saveImageToAlbum(file);
                    }}
                  >
                    {savingImagePath === file.path ? "保存中" : "保存相册"}
                  </Text>
                </View>
              ) : (
                <Text className="file-action">
                  {openingPath === file.path
                    ? "打开中"
                    : isDocumentArtifact(file)
                      ? "打开文件"
                      : "查看文件"}
                </Text>
              )}
            </View>
          ))}
        {!loading && !errorMessage && files.length === 0 && (
          <StateView
            type="empty"
            title="暂无产物文件"
            description="任务生成结果后，会自动归档到这里"
          />
        )}
      </View>
    </AppShell>
  );
}
