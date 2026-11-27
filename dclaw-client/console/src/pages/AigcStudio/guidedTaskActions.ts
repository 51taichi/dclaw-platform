import {
  superExpertPlatformApi,
  type BoundAigcTask,
} from "../../api/modules/superExpertPlatform";

export interface GuidedTaskSubmission {
  submitted: true;
}

export async function getGuidedConversationRoute(
  task: BoundAigcTask,
): Promise<string> {
  const route = await superExpertPlatformApi.getConversationRoute(
    task.binding.conversation_id,
  );
  if (
    route.conversation_id !== task.binding.conversation_id ||
    !route.chat_id?.trim()
  ) {
    throw new Error("原任务会话绑定无效");
  }
  return `/task/${encodeURIComponent(route.chat_id)}`;
}

export async function submitGuidedTaskAsset(
  task: BoundAigcTask,
  assetId: string,
): Promise<GuidedTaskSubmission> {
  if (!assetId) throw new Error("当前绑定节点还没有可提交的成品");
  const selection = assetId;
  const currentVersion = Number.isInteger(task.version)
    ? (task.version as number)
    : null;
  const submissionVersion =
    task.status === "SUBMITTED" && currentVersion !== null && currentVersion > 0
      ? currentVersion - 1
      : currentVersion ?? "unknown";
  const storageKey = `dclaw:aigc-submit:${task.binding.material_task_id}:${submissionVersion}:${selection}`;
  const eventId = localStorage.getItem(storageKey) || crypto.randomUUID();
  localStorage.setItem(storageKey, eventId);
  const result = await superExpertPlatformApi.command("aigc.asset.submit", {
    installation_id: task.binding.installation_id,
    contract_version: "1",
    idempotency_key: eventId,
    arguments: {
      event_id: eventId,
      binding: task.binding,
      asset_id: assetId,
    },
  });
  const persisted = result.task;
  if (
    !persisted ||
    persisted.binding.material_task_id !== task.binding.material_task_id ||
    persisted.asset_id !== assetId
  ) {
    throw new Error("未取得有效的素材提交回执，请刷新任务状态后重试");
  }
  if (persisted.status !== "ACCEPTED") {
    throw new Error(
      `素材任务尚未完成（当前状态：${persisted.status}），请留在当前页面重试`,
    );
  }
  return {
    submitted: true,
  };
}
