import {
  superExpertPlatformApi,
  type BoundAigcTask,
} from "../../api/modules/superExpertPlatform";

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
  reviewAssets?: { node_id: string; asset_id: string }[],
): Promise<boolean> {
  if (!assetId) throw new Error("当前绑定节点还没有可提交的成品");
  const selection = reviewAssets?.length
    ? JSON.stringify(reviewAssets)
    : assetId;
  const storageKey = `dclaw:aigc-submit:${task.binding.material_task_id}:${selection}`;
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
      ...(reviewAssets?.length ? { review_assets: reviewAssets } : {}),
    },
  });
  const persisted = result.task;
  if (
    !persisted ||
    persisted.binding.material_task_id !== task.binding.material_task_id ||
    persisted.asset_id !== assetId ||
    (reviewAssets?.length &&
      JSON.stringify(persisted.review_assets) !==
        JSON.stringify(reviewAssets)) ||
    !["SUBMITTED", "ACCEPTED", "REVISION_REQUIRED"].includes(persisted.status)
  ) {
    throw new Error("未取得有效的素材提交回执，请刷新任务状态后重试");
  }
  return true;
}
