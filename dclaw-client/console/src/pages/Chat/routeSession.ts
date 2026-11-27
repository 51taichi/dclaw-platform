export function getRouteChatId(pathname: string): string | undefined {
  const match = pathname.match(/^\/(?:task|claw)\/([^/?#]+)/);
  if (!match?.[1]) return undefined;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export function buildAigcTaskRoute(taskId: string): string {
  return `/aigc-studio?task=${encodeURIComponent(taskId)}`;
}
