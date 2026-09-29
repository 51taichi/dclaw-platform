import { save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";

const safeDownloadName = (filename: string) => {
  const basename = filename.split(/[\\/]/).filter(Boolean).pop() || "download";
  return basename.replace(/[<>:"/\\|?*]+/g, "-").trim() || "download";
};

const isTauriRuntime = () =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function saveWithPywebview(blob: Blob, filename: string) {
  const saveBlob = window.pywebview?.api?.save_blob;
  if (!saveBlob) return null;
  const bytes = Array.from(new Uint8Array(await blob.arrayBuffer()));
  return saveBlob(bytes, filename);
}

function saveWithBrowser(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noreferrer";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Save a downloaded payload using the host's standard interaction.
 *
 * Desktop clients show the operating system's Save As dialog. Browsers keep
 * their native download behavior. `false` means the user cancelled the dialog.
 */
export async function saveDownloadedBlob(blob: Blob, filename: string) {
  const safeName = safeDownloadName(filename);
  if (isTauriRuntime()) {
    const destination = await save({
      defaultPath: safeName,
      title: "保存文件",
    });
    if (!destination) return false;
    await writeFile(destination, new Uint8Array(await blob.arrayBuffer()));
    return true;
  }

  const pywebviewResult = await saveWithPywebview(blob, safeName);
  if (pywebviewResult !== null) return pywebviewResult;

  saveWithBrowser(blob, safeName);
  return true;
}
