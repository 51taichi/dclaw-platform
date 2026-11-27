import { getSceneIcon, normalizeSceneIcon } from "./sceneIconConfig";

export function SceneIcon({
  name,
  size = 16,
}: {
  name?: string;
  size?: number;
}) {
  const normalized = normalizeSceneIcon(name);
  const Icon = getSceneIcon(normalized);
  return <Icon size={size} aria-hidden="true" data-scene-icon={normalized} />;
}
