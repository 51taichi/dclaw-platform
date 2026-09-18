import { Markdown } from "@agentscope-ai/chat";
import { useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { ExpertIdentityContext } from "../../../contexts/ExpertIdentityContext";
import { message } from "antd";
import { superExpertPlatformApi } from "../../../api/modules/superExpertPlatform";
import { toDisplayUrl } from "../utils";
import styles from "./RuntimeProgressCard.module.less";

interface RuntimeContent {
  type?: string;
  text?: string;
  refusal?: string;
  status?: string;
  image_url?: string;
  source?: {
    type?: string;
    url?: string;
  };
  data?: Record<string, any>;
}

interface RuntimeMessage {
  id?: string;
  role?: string;
  type?: string;
  status?: string;
  content?: RuntimeContent[];
  metadata?: Record<string, any> | null;
}

interface RuntimeResponse {
  id?: string;
  status?: string;
  output?: RuntimeMessage[];
}

interface ReviewBundleMetadata {
  material_task_id: string;
  assets: Array<{ asset_id: string }>;
}

import SuperExpertBadge from "../../../components/SuperExpertBadge";
import {
  expertIdentity,
  type ExpertIdentity,
} from "../../../utils/expertIdentity";

interface Props {
  identity?: ExpertIdentity;
  data: RuntimeResponse;
  isLast?: boolean;
  chatId?: string | null;
  agentId?: string | null;
  interactionContent?: ReactNode;
}

const TOOL_LABELS: Record<string, string> = {
  edit_file: "修改文件",
  write_file: "写入文件",
  read_file: "读取文件",
  execute_shell_command: "执行命令",
  list_files: "浏览文件",
  search_files: "搜索文件",
};

function isRunning(status?: string) {
  return status === "created" || status === "in_progress";
}

const IMAGEGEN_PATH_PATTERN =
  /(?:`?)(?:\/app\/working\/(?:workspaces\/[^/\s`]+\/)?sessions_data\/(?:<session_id>|[^/\s`]+)\/)?media\/imagegen\/imagegen_[\w.-]+\.(?:png|jpe?g|webp|gif)(?:`?)/i;
const INTERACTION_DELIVERY_PREFIX =
  /^\s*(?:(?:好(?:了|的)?|可以|行)[，,。.!！；;：:]?\s*)?(?:(?:这张|这个|该|交互)?卡片)(?:已经|已)?(?:发(?:送)?(?:给你|过去|出去|出)?|发送成功|创建(?:好|完成|成功))了?(?:\s*[，,。.!！；;：:]\s*|\s*$)/;

function sanitizeGeneratedImagePathText(text: string) {
  let imageReferenceIndex = 0;
  return text
    .split(/\r?\n/)
    .map((line) => {
      if (!IMAGEGEN_PATH_PATTERN.test(line)) return line;
      imageReferenceIndex += 1;
      const bullet = line.match(/^(\s*[-*]\s*)/)?.[1] || "";
      const schemeLabel = line.match(/方案\s*([一二三四五六七八九十\d]+)/)?.[0];
      const label =
        schemeLabel?.replace(/\s+/g, "") || `图片 ${imageReferenceIndex}`;
      return `${bullet}${label}：见下方图片 ${imageReferenceIndex}`;
    })
    .join("\n")
    .replace(/\n{3,}/g, "\n\n");
}

function sanitizeInteractionDeliveryStatusText(text: string) {
  return text.replace(INTERACTION_DELIVERY_PREFIX, "");
}

function getText(messageItem: RuntimeMessage) {
  return (messageItem.content || [])
    .map((content) => {
      if (content.type === "text") {
        return sanitizeGeneratedImagePathText(content.text || "");
      }
      if (content.type === "refusal") {
        return sanitizeGeneratedImagePathText(content.refusal || "");
      }
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function cleanVisualSchemeName(value: string) {
  const name = value
    .split(/[（(]/)[0]
    .split(/\s[-–—]\s/)[0]
    .trim()
    .replace(/^["'“”‘’]+|["'“”‘’]+$/g, "");
  if (
    /(?:\/app\/working|media\/(?:imagegen|ppt_visual_schemes)|imagegen_[\w.-]+\.(?:png|jpe?g|webp|gif))/i.test(
      name,
    )
  ) {
    return "";
  }
  return name;
}

function extractVisualSchemeNames(text: string) {
  const names: string[] = [];
  const patterns = [
    /Style direction\s*[:：]\s*([^\r\n]+)/gi,
    /(?:方案|方向)\s*[一二三四五六七八九十\dA-Z]*\s*[:：]\s*([^\r\n]+)/gi,
  ];
  for (const pattern of patterns) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      const name = cleanVisualSchemeName(match[1] || "");
      if (name && !names.includes(name)) {
        names.push(name);
      }
    }
  }
  return names;
}

function getImageUrl(
  content: RuntimeContent,
  chatId?: string | null,
  agentId?: string | null,
) {
  let rawUrl = "";
  if (
    (content.type === "image" || content.type === "image_url") &&
    typeof content.image_url === "string" &&
    content.image_url
  ) {
    rawUrl = content.image_url;
  }
  if (
    !rawUrl &&
    content.type === "image" &&
    content.source?.type === "url" &&
    typeof content.source.url === "string"
  ) {
    rawUrl = content.source.url;
  }
  return rawUrl
    ? toDisplayUrl(rawUrl, chatId || undefined, agentId || undefined)
    : "";
}

function hasVisibleMessageContent(messageItem: RuntimeMessage) {
  if (getText(messageItem).trim()) return true;
  return (messageItem.content || []).some((content) => getImageUrl(content));
}

function isToolMessage(type?: string) {
  return [
    "plugin_call",
    "function_call",
    "component_call",
    "mcp_call",
  ].includes(type || "");
}

function isToolOutput(type?: string) {
  return [
    "plugin_call_output",
    "function_call_output",
    "component_call_output",
    "mcp_call_output",
  ].includes(type || "");
}

function findPendingInteractionId(value: unknown, depth = 0): string | null {
  if (depth > 5 || value == null) return null;
  if (typeof value === "string") {
    try {
      return findPendingInteractionId(JSON.parse(value), depth + 1);
    } catch {
      return null;
    }
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const interactionId = findPendingInteractionId(item, depth + 1);
      if (interactionId) return interactionId;
    }
    return null;
  }
  if (typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const interaction = record.interaction;
  if (interaction && typeof interaction === "object") {
    const interactionId = (interaction as Record<string, unknown>)
      .interaction_id;
    const interactionStatus = (interaction as Record<string, unknown>).status;
    if (
      interactionStatus === "PENDING" &&
      typeof interactionId === "string" &&
      interactionId.trim()
    ) {
      return interactionId;
    }
  }
  for (const key of ["text", "output", "result", "content"]) {
    const interactionId = findPendingInteractionId(record[key], depth + 1);
    if (interactionId) return interactionId;
  }
  return null;
}

function getCreatedInteractionIds(messageItem: RuntimeMessage) {
  const interactionIds: string[] = [];
  const addInteractionId = (value: unknown) => {
    if (
      typeof value === "string" &&
      value.trim() &&
      !interactionIds.includes(value.trim())
    ) {
      interactionIds.push(value.trim());
    }
  };
  const addMetadataInteractionIds = (value: unknown) => {
    if (!value || typeof value !== "object") return;
    const metadata = value as Record<string, unknown>;
    const listedIds = metadata.super_expert_interaction_ids;
    if (Array.isArray(listedIds)) {
      listedIds.forEach(addInteractionId);
    }
    addInteractionId(metadata.super_expert_interaction_id);
  };

  addMetadataInteractionIds(messageItem.metadata);
  addMetadataInteractionIds(messageItem.metadata?.metadata);
  if (interactionIds.length) return interactionIds;
  if (!isToolOutput(messageItem.type)) return interactionIds;
  for (const content of messageItem.content || []) {
    const data = content.data;
    if (data?.name !== "interaction_card_create") continue;
    const interactionId = findPendingInteractionId(data.output);
    if (interactionId) addInteractionId(interactionId);
  }
  return interactionIds;
}

function getReviewBundleMetadata(
  messageItem: RuntimeMessage,
): ReviewBundleMetadata | null {
  const candidates = [messageItem.metadata, messageItem.metadata?.metadata];
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") continue;
    const bundle = (candidate as Record<string, unknown>)
      .dclaw_aigc_review_bundle;
    if (!bundle || typeof bundle !== "object") continue;
    const record = bundle as Record<string, unknown>;
    if (
      typeof record.material_task_id !== "string" ||
      !record.material_task_id.trim() ||
      !Array.isArray(record.assets)
    ) {
      continue;
    }
    const assets = record.assets.filter((item): item is { asset_id: string } =>
      Boolean(
        item &&
          typeof item === "object" &&
          typeof (item as Record<string, unknown>).asset_id === "string" &&
          String((item as Record<string, unknown>).asset_id).trim(),
      ),
    );
    if (!assets.length) continue;
    return {
      material_task_id: record.material_task_id,
      assets,
    };
  }
  return null;
}

function interactionDeliveryMessages(output: RuntimeMessage[]) {
  const messages = new Set<RuntimeMessage>();
  let awaitingReplyAfterCreate = false;
  for (const item of output) {
    const interactionIds = getCreatedInteractionIds(item);
    if (interactionIds.length && isToolOutput(item.type)) {
      awaitingReplyAfterCreate = true;
    }
    if (
      (item.type === "message" || item.type === "error") &&
      hasVisibleMessageContent(item)
    ) {
      if (interactionIds.length || awaitingReplyAfterCreate) {
        messages.add(item);
        awaitingReplyAfterCreate = false;
      }
    }
  }
  return messages;
}

function targetOf(args: Record<string, any> = {}) {
  const target =
    args.file_path ||
    args.path ||
    args.filename ||
    args.file ||
    args.command ||
    args.query ||
    "";
  if (typeof target !== "string") return "";
  const parts = target.split("/");
  return parts.length > 3 ? `.../${parts.slice(-3).join("/")}` : target;
}

function summarizeTools(messages: RuntimeMessage[]) {
  const tools = messages
    .filter((item) => isToolMessage(item.type))
    .map((item) => {
      const data = item.content?.[0]?.data || {};
      const name = String(data.name || "");
      const args = data.arguments || {};
      return {
        name,
        label: TOOL_LABELS[name] || name || "工具调用",
        target: targetOf(args),
        running: isRunning(item.status),
      };
    })
    .filter((item) => item.name);

  const counts = new Map<string, number>();
  for (const tool of tools) {
    counts.set(tool.label, (counts.get(tool.label) || 0) + 1);
  }

  return {
    tools,
    counts: Array.from(counts.entries()).map(([label, count]) => ({
      label,
      count,
    })),
    activeTool: tools.find((tool) => tool.running) || tools[tools.length - 1],
  };
}

function extractCopyText(
  messages: RuntimeMessage[],
  interactionDeliveryItems: Set<RuntimeMessage>,
) {
  return messages
    .filter((item) => !getReviewBundleMetadata(item))
    .map((item) => {
      const text = getText(item);
      return interactionDeliveryItems.has(item)
        ? sanitizeInteractionDeliveryStatusText(text)
        : text;
    })
    .filter(Boolean)
    .join("\n\n");
}

export default function RuntimeProgressCard(props: Props) {
  const currentIdentity = useContext(ExpertIdentityContext);
  const identity = currentIdentity || props.identity || expertIdentity();
  const [previewImage, setPreviewImage] = useState<{
    url: string;
    alt: string;
  } | null>(null);
  const [downloadingReviewTaskId, setDownloadingReviewTaskId] = useState<
    string | null
  >(null);
  const outputOrderRef = useRef<{
    responseId?: string;
    messageIds: string[];
  }>({ responseId: props.data.id, messageIds: [] });
  if (outputOrderRef.current.responseId !== props.data.id) {
    outputOrderRef.current = { responseId: props.data.id, messageIds: [] };
  }

  const incomingOutput = props.data.output || [];
  for (const item of incomingOutput) {
    if (item.id && !outputOrderRef.current.messageIds.includes(item.id)) {
      outputOrderRef.current.messageIds.push(item.id);
    }
  }
  const positionById = new Map(
    outputOrderRef.current.messageIds.map((id, index) => [id, index]),
  );
  const output = incomingOutput
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftPosition = left.item.id
        ? positionById.get(left.item.id)
        : undefined;
      const rightPosition = right.item.id
        ? positionById.get(right.item.id)
        : undefined;
      if (leftPosition === undefined || rightPosition === undefined) {
        return left.index - right.index;
      }
      return leftPosition - rightPosition;
    })
    .map(({ item }) => item);
  const visibleMessages = output.filter((item) => {
    if (item.type !== "message" && item.type !== "error") return false;
    return hasVisibleMessageContent(item);
  });
  const reasoningCount = output.filter(
    (item) => item.type === "reasoning",
  ).length;
  const toolOutputCount = output.filter((item) =>
    isToolOutput(item.type),
  ).length;
  const { tools, counts, activeTool } = useMemo(
    () => summarizeTools(output),
    [output],
  );
  const interactionDeliveryItems = interactionDeliveryMessages(output);
  const copyText = extractCopyText(visibleMessages, interactionDeliveryItems);
  const running = isRunning(props.data.status);
  const hasActivity = tools.length > 0 || reasoningCount > 0;

  if (!visibleMessages.length && !hasActivity && running) {
    return (
      <div className={styles.runtimeCard} data-runtime-progress-card>
        <div className={styles.agentHeader}>
          <img
            className={styles.avatar}
            src={identity.avatar}
            alt={identity.name}
          />
          <span>{identity.name}</span>
          {identity.isSuperExpert && <SuperExpertBadge />}
        </div>
        <div className={styles.activity}>
          <div className={styles.summary}>
            <span className={styles.dot} />
            <span className={styles.summaryText}>正在思考下一步...</span>
          </div>
        </div>
      </div>
    );
  }

  let imageOrdinal = 0;

  return (
    <div className={styles.runtimeCard} data-runtime-progress-card>
      <div className={styles.agentHeader}>
        <img
          className={styles.avatar}
          src={identity.avatar}
          alt={identity.name}
        />
        <span>{identity.name}</span>
        {identity.isSuperExpert && <SuperExpertBadge />}
      </div>

      {output.map((item, index) => {
        const interactionIds = getCreatedInteractionIds(item);
        if (interactionIds.length && isToolOutput(item.type)) {
          return (
            <div key={`interactions-${item.id || index}`}>
              {interactionIds.map((interactionId) => (
                <div
                  key={`interaction-${interactionId}`}
                  data-super-expert-interaction-slot={interactionId}
                />
              ))}
            </div>
          );
        }
        if (
          (item.type !== "message" && item.type !== "error") ||
          !hasVisibleMessageContent(item)
        ) {
          return null;
        }
        const reviewBundle = getReviewBundleMetadata(item);
        if (reviewBundle) {
          const reviewImages = (item.content || [])
            .map((content) => getImageUrl(content, props.chatId, props.agentId))
            .filter(Boolean);
          if (!reviewImages.length) return null;
          const downloading =
            downloadingReviewTaskId === reviewBundle.material_task_id;
          return (
            <section
              key={item.id || index}
              className={styles.reviewAssetsCard}
              role="region"
              aria-label="审核素材"
              data-review-assets-card={reviewBundle.material_task_id}
            >
              <div className={styles.reviewAssetsRow}>
                {reviewImages.map((imageUrl, imageIndex) => (
                  <button
                    key={`${imageUrl}-${imageIndex}`}
                    type="button"
                    className={styles.reviewAssetButton}
                    onClick={() =>
                      setPreviewImage({
                        url: imageUrl,
                        alt: `审核图片 ${imageIndex + 1}`,
                      })
                    }
                    title="点击查看大图"
                  >
                    <img src={imageUrl} alt={`审核图片 ${imageIndex + 1}`} />
                  </button>
                ))}
              </div>
              <button
                type="button"
                className={styles.reviewAssetsDownload}
                disabled={downloading}
                onClick={() => {
                  setDownloadingReviewTaskId(reviewBundle.material_task_id);
                  void superExpertPlatformApi
                    .downloadReviewAssets(reviewBundle.material_task_id)
                    .catch(() => {
                      message.error("批量下载失败，请稍后重试");
                    })
                    .finally(() => setDownloadingReviewTaskId(null));
                }}
              >
                {downloading ? (
                  <>
                    <span className={styles.downloadSpinner} aria-hidden />
                    正在打包
                  </>
                ) : (
                  "批量下载"
                )}
              </button>
            </section>
          );
        }
        return (
          <div key={item.id || index} className={styles.messageContent}>
            {(() => {
              const itemText = (item.content || [])
                .map((content) => content.text || content.refusal || "")
                .join("\n");
              const imageLabels = extractVisualSchemeNames(itemText);
              let messageImageIndex = 0;
              let shouldSanitizeInteractionPrefix =
                interactionDeliveryItems.has(item);

              return (item.content || []).map((content, contentIndex) => {
                if (content.type === "text" && content.text) {
                  const text = sanitizeGeneratedImagePathText(content.text);
                  const sanitizeThisBlock =
                    shouldSanitizeInteractionPrefix && Boolean(text.trim());
                  if (text.trim()) shouldSanitizeInteractionPrefix = false;
                  return (
                    <Markdown
                      key={`text-${contentIndex}`}
                      content={
                        sanitizeThisBlock
                          ? sanitizeInteractionDeliveryStatusText(text)
                          : text
                      }
                      cursor={
                        running &&
                        item === visibleMessages[visibleMessages.length - 1]
                      }
                    />
                  );
                }
                if (content.type === "refusal" && content.refusal) {
                  const refusal = sanitizeGeneratedImagePathText(
                    content.refusal,
                  );
                  const sanitizeThisBlock =
                    shouldSanitizeInteractionPrefix && Boolean(refusal.trim());
                  if (refusal.trim()) shouldSanitizeInteractionPrefix = false;
                  return (
                    <Markdown
                      key={`refusal-${contentIndex}`}
                      content={
                        sanitizeThisBlock
                          ? sanitizeInteractionDeliveryStatusText(refusal)
                          : refusal
                      }
                      cursor={
                        running &&
                        item === visibleMessages[visibleMessages.length - 1]
                      }
                    />
                  );
                }
                const imageUrl = getImageUrl(
                  content,
                  props.chatId,
                  props.agentId,
                );
                if (!imageUrl) return null;
                imageOrdinal += 1;
                const imageLabel = imageLabels[messageImageIndex];
                messageImageIndex += 1;
                const alt = imageLabel || `对话图片 ${imageOrdinal}`;
                return (
                  <button
                    key={`image-${contentIndex}`}
                    type="button"
                    className={styles.inlineImageButton}
                    onClick={() => setPreviewImage({ url: imageUrl, alt })}
                    title="点击查看大图"
                  >
                    {imageLabel && (
                      <span className={styles.inlineImageLabel}>
                        {imageLabel}
                      </span>
                    )}
                    <img src={imageUrl} alt={alt} />
                  </button>
                );
              });
            })()}
            {interactionIds.map((interactionId) => (
              <div
                key={`interaction-${interactionId}`}
                data-super-expert-interaction-slot={interactionId}
              />
            ))}
          </div>
        );
      })}

      <div data-super-expert-interaction-fallback-slot />
      {props.interactionContent}

      {hasActivity && (
        <div className={styles.activity}>
          <div className={styles.summary}>
            <span
              className={`${styles.dot} ${running ? "" : styles.dotDone}`}
            />
            <span className={styles.summaryText}>
              {running
                ? activeTool
                  ? `正在${activeTool.label}${
                      activeTool.target ? `：${activeTool.target}` : ""
                    }`
                  : "正在分析任务..."
                : `已完成 ${
                    tools.length + reasoningCount + toolOutputCount
                  } 项处理`}
            </span>
            <div className={styles.chips}>
              {counts.slice(0, 3).map((item) => (
                <span key={item.label} className={styles.chip}>
                  {item.label} {item.count}
                </span>
              ))}
              {reasoningCount > 0 && (
                <span className={styles.chip}>思考 {reasoningCount}</span>
              )}
            </div>
          </div>

          {tools.length > 0 && (
            <details className={styles.details}>
              <summary className={styles.detailsSummary}>查看详细操作</summary>
              <div className={styles.detailList}>
                {tools.slice(-12).map((tool, index) => (
                  <div
                    key={`${tool.name}-${tool.target}-${index}`}
                    className={`${styles.detailItem} ${
                      tool.target ? "" : styles.detailItemSingle
                    }`}
                  >
                    <span className={styles.detailName} title={tool.label}>
                      {tool.label}
                    </span>
                    {tool.target && (
                      <span className={styles.detailTarget} title={tool.target}>
                        {tool.target}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {copyText && !running && (
        <div className={styles.copyRow}>
          <button
            type="button"
            className={styles.copyButton}
            onClick={() => {
              void navigator.clipboard.writeText(copyText).then(() => {
                message.success("已复制");
              });
            }}
          >
            复制回复
          </button>
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
}
