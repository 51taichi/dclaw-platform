import { invoke } from "@tauri-apps/api/core";

interface NativeClipboardAttachment {
  name: string;
  mime_type: string;
  base64_data: string;
}

const decodeBase64 = (encoded: string) => {
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
};

export const isDesktopRuntime = () =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function readDesktopClipboardFiles(): Promise<File[]> {
  if (!isDesktopRuntime()) return [];

  const attachments = await invoke<NativeClipboardAttachment[]>(
    "read_clipboard_attachments",
  );
  return attachments.map(
    (attachment) =>
      new File([decodeBase64(attachment.base64_data)], attachment.name, {
        type: attachment.mime_type,
      }),
  );
}
