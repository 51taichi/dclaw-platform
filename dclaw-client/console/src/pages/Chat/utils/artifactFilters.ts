const INTERNAL_TASK_FILE_NAMES = new Set([
  "agent.json",
  "agent_config.json",
  "memory_file_metadata.json",
  "MEMORY.md",
  "HEARTBEAT.md",
  "BOOTSTRAP.md",
  "SOUL.md",
  "PROFILE.md",
  "AGENTS.md",
  "jobs.json",
  "chats.json",
  "config.json",
  "cloud_docs.json",
  "skills.json",
  "skill.json",
  "token_usage.json",
  "qwenpaw_app.log",
  "qwenpaw_app_new.log",
  "overview.md.lock",
  ".bootstrap_completed",
  ".reme_store_v1",
  ".skill.json.lock",
]);

const INTERNAL_TASK_DIR_NAMES = new Set([
  ".git",
  ".github",
  ".gemini",
  "__pycache__",
  ".pytest_cache",
  "browser",
  "cloud_docs",
  "dialog",
  "draft",
  "embedding_cache",
  "file_store",
  "logs",
  "memory",
  "missions",
  "node_modules",
  "sessions",
  "skills",
  "tool_result",
  "tool_results",
  "_work",
  "attachments",
  "input",
  "inputs",
  "source",
  "sources",
  "uploads",
  "上传",
  "附件",
  "输入",
  "原始资料",
  "参考资料",
  "补充资料",
  "资料库",
  "venv",
]);

const PRIMARY_DELIVERABLE_EXTENSIONS = new Set([
  "docx",
  "html",
  "htm",
  "pdf",
  "pptx",
  "xlsx",
]);

const IMAGEGEN_MEDIA_PATTERN =
  /(^|\/)media\/imagegen\/imagegen_[^/]+\.(?:png|jpe?g|webp|gif|bmp|svg)$/i;

export function isInternalTaskFile(path: string): boolean {
  const parts = path.split("/").filter(Boolean);
  if (parts.length === 0) return true;

  if (parts.some((part) => part.startsWith("."))) return true;
  if (
    parts
      .slice(0, -1)
      .some((part) => part === "render_qa" || part.endsWith("_render_qa"))
  ) {
    return true;
  }
  if (parts.slice(0, -1).some((part) => INTERNAL_TASK_DIR_NAMES.has(part))) {
    return true;
  }

  const filename = parts[parts.length - 1];
  if (INTERNAL_TASK_FILE_NAMES.has(filename)) return true;
  if (filename.endsWith(".presentation.compose.json")) return true;
  if (filename.endsWith(".lock") || filename.endsWith(".log")) return true;

  return false;
}

export function filterUserTaskFiles(files: string[]): string[] {
  const seen = new Set<string>();
  const filtered = files.filter((file) => {
    if (!file || isInternalTaskFile(file) || seen.has(file)) return false;
    seen.add(file);
    return true;
  });
  const hasPrimaryDeliverable = filtered.some((file) => {
    const ext = file.split(".").pop()?.toLowerCase() || "";
    return PRIMARY_DELIVERABLE_EXTENSIONS.has(ext);
  });
  if (!hasPrimaryDeliverable) return filtered;
  return filtered.filter((file) => !IMAGEGEN_MEDIA_PATTERN.test(file));
}
