import Taro from "@tarojs/taro";

import { buildRequestUrl } from "./api";
import { getAuthToken } from "./auth";

export interface LocalAttachmentInput {
  path: string;
  name: string;
}

export interface UploadedAttachment {
  name: string;
  url: string;
  markdown: string;
}

interface UploadResponsePayload {
  url?: string;
  file_name?: string;
}

function parseUploadPayload(data: string): UploadResponsePayload {
  try {
    return JSON.parse(data) as UploadResponsePayload;
  } catch {
    return {};
  }
}

export async function uploadConsoleAttachment(
  input: LocalAttachmentInput,
): Promise<UploadedAttachment> {
  const token = getAuthToken();
  const response = await Taro.uploadFile({
    url: buildRequestUrl("/api/user", "/console/upload"),
    filePath: input.path,
    name: "file",
    header: token ? { Authorization: `Bearer ${token}` } : undefined,
  });

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(`附件上传失败：${response.statusCode}`);
  }

  const payload = parseUploadPayload(String(response.data || ""));
  const url = payload.url || "";
  const name = payload.file_name || input.name;
  if (!url) {
    throw new Error("附件上传失败：缺少文件地址");
  }

  return {
    name,
    url,
    markdown: `📎 [${name}](${url})`,
  };
}
