import type { ClientScene } from "../../api/modules/auth";
import { openExternalLink } from "../../utils/openExternalLink";

export function isSafeSceneUrl(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

export function openSceneInExternalBrowser(
  scenes: ClientScene[],
  key: string,
): boolean {
  const scene = scenes.find(
    (item) => item.key === key && isSafeSceneUrl(item.url),
  );
  if (!scene) {
    return false;
  }

  openExternalLink(scene.url);
  return true;
}
