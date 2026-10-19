/* eslint-disable react-refresh/only-export-components */
import { Bubble } from "@agentscope-ai/chat";
import { Tooltip } from "antd";
import { FolderOpen } from "lucide-react";
import { useMemo } from "react";
import { toDisplayUrl } from "../../pages/Chat/utils";
import styles from "./index.module.less";

export const ATTACHMENT_FILES_CARD = "DClawAttachmentFiles";

interface ContentPart {
  type?: string;
  text?: string;
  image_url?: string;
  video_url?: string;
  video_poster?: string;
  audio_url?: string;
  data?: string;
  file_url?: string;
  file_id?: string;
  filename?: string;
  file_name?: string;
  fileName?: string;
  file_size?: number;
}

interface RequestCardData {
  input?: Array<{
    content?: ContentPart[];
  }>;
}

export interface UserRequestCardProps {
  data: RequestCardData;
  chatId?: string;
  agentId?: string;
}

export interface AttachmentFile {
  name: string;
  url: string;
  size?: number;
}

export function resolveRequestAttachmentUrl(
  url: string,
  chatId?: string,
  agentId?: string,
): string {
  const displayUrl = toDisplayUrl(url, chatId, agentId);
  if (
    !chatId ||
    (!displayUrl.includes("/api/") && !displayUrl.includes("/console/"))
  ) {
    return displayUrl;
  }

  const params: string[] = [];
  if (!/[?&]chatId=/u.test(displayUrl)) {
    params.push(`chatId=${encodeURIComponent(chatId)}`);
  }
  if (agentId && !/[?&]agent_id=/u.test(displayUrl)) {
    params.push(`agent_id=${encodeURIComponent(agentId)}`);
  }
  if (params.length === 0) return displayUrl;

  const separator = displayUrl.includes("?") ? "&" : "?";
  return `${displayUrl}${separator}${params.join("&")}`;
}

interface RequestBubbleCard {
  code: string;
  data: unknown;
}

const ATTACHMENT_MARKDOWN = /^\s*📎 \[(.+)\]\((.+)\)\s*$/u;
const EXTRACTED_BODY_START = /^\s*\[附件正文开始：.*\]\s*$/u;
const EXTRACTED_BODY_END = /^\s*\[附件正文结束：.*\]\s*$/u;
const UPLOAD_SUMMARY_PREFIX = "已上传附件：";

function sanitizeAttachmentText(
  text: string,
  structuredFileNames: Set<string>,
): { text: string; files: AttachmentFile[] } {
  const keptLines: string[] = [];
  const files: AttachmentFile[] = [];
  let insideExtractedBody = false;

  for (const line of text.split(/\r?\n/u)) {
    if (EXTRACTED_BODY_START.test(line)) {
      insideExtractedBody = true;
      continue;
    }
    if (insideExtractedBody) {
      if (EXTRACTED_BODY_END.test(line)) {
        insideExtractedBody = false;
      }
      continue;
    }

    const attachment = line.match(ATTACHMENT_MARKDOWN);
    if (attachment) {
      files.push({ name: attachment[1].trim(), url: attachment[2].trim() });
      continue;
    }

    const trimmed = line.trim();
    if (trimmed.startsWith(UPLOAD_SUMMARY_PREFIX)) {
      const names = trimmed
        .slice(UPLOAD_SUMMARY_PREFIX.length)
        .split("、")
        .map((name) => name.trim())
        .filter(Boolean);
      if (
        names.length > 0 &&
        names.every((name) => structuredFileNames.has(name))
      ) {
        continue;
      }
    }

    keptLines.push(line);
  }

  return {
    text: keptLines.join("\n").trim(),
    files,
  };
}

function fallbackFileName(url: string): string {
  const path = url.split(/[?#]/u)[0];
  const basename = path.split(/[\\/]/u).filter(Boolean).pop() || "file";
  try {
    return decodeURIComponent(basename);
  } catch {
    return basename;
  }
}

export function buildUserRequestCards(
  content: ContentPart[],
  resolveUrl: (url: string) => string = (url) => url,
): RequestBubbleCard[] {
  const cards: RequestBubbleCard[] = [];
  const seenFiles = new Set<string>();
  const structuredFileNames = new Set(
    content
      .filter((part) => part.type === "file")
      .map((part) => part.filename || part.file_name || part.fileName || "")
      .filter(Boolean),
  );

  const appendFiles = (files: AttachmentFile[]) => {
    const uniqueFiles = files
      .map((file) => ({ ...file, url: resolveUrl(file.url) }))
      .filter((file) => {
        const key = `${file.name}\u0000${file.url}`;
        if (seenFiles.has(key)) return false;
        seenFiles.add(key);
        return true;
      });
    if (uniqueFiles.length === 0) return;

    const previous = cards[cards.length - 1];
    if (previous?.code === ATTACHMENT_FILES_CARD) {
      previous.data = [...(previous.data as AttachmentFile[]), ...uniqueFiles];
      return;
    }
    cards.push({ code: ATTACHMENT_FILES_CARD, data: uniqueFiles });
  };

  for (const part of content) {
    if (part.type === "text" && typeof part.text === "string") {
      const sanitized = sanitizeAttachmentText(part.text, structuredFileNames);
      if (sanitized.text) {
        cards.push({
          code: "Text",
          data: { content: sanitized.text, raw: true },
        });
      }
      appendFiles(sanitized.files);
      continue;
    }

    if (part.type === "file") {
      const rawUrl = part.file_url || part.file_id || "";
      const name =
        part.filename ||
        part.file_name ||
        part.fileName ||
        fallbackFileName(rawUrl);
      appendFiles([{ name, url: rawUrl, size: part.file_size }]);
      continue;
    }

    if (part.type === "image" && part.image_url) {
      cards.push({
        code: "Images",
        data: [{ url: resolveUrl(part.image_url) }],
      });
      continue;
    }

    if (part.type === "video" && part.video_url) {
      cards.push({
        code: "Videos",
        data: [
          {
            src: resolveUrl(part.video_url),
            poster: part.video_poster
              ? resolveUrl(part.video_poster)
              : undefined,
          },
        ],
      });
      continue;
    }

    if (part.type === "audio" && (part.audio_url || part.data)) {
      cards.push({
        code: "Audios",
        data: [{ src: resolveUrl(part.audio_url || part.data || "") }],
      });
    }
  }

  return cards;
}

export function AttachmentFilesCard({ data }: { data: AttachmentFile[] }) {
  return (
    <div className={styles.attachmentList}>
      {data.map((file, index) => (
        <div
          className={styles.attachmentRow}
          key={`${file.name}:${file.url}:${index}`}
        >
          <span className={styles.attachmentName}>{`📎 [${file.name}]`}</span>
          {file.url ? (
            <Tooltip title="打开文件">
              <button
                type="button"
                className={styles.openButton}
                aria-label={`打开文件 ${file.name}`}
                onClick={() =>
                  window.open(file.url, "_blank", "noopener,noreferrer")
                }
              >
                <FolderOpen aria-hidden="true" size={16} strokeWidth={1.8} />
              </button>
            </Tooltip>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function UserRequestCard({
  data,
  chatId,
  agentId,
}: UserRequestCardProps) {
  const cards = useMemo(
    () =>
      buildUserRequestCards(data.input?.[0]?.content || [], (url) =>
        resolveRequestAttachmentUrl(url, chatId, agentId),
      ),
    [agentId, chatId, data.input],
  );

  if (cards.length === 0) return null;
  return <Bubble role="user" cards={cards} />;
}
