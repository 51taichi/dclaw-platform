import { useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { superExpertPlatformApi } from "../../api/modules/superExpertPlatform";
import { useAgentStore } from "../../stores/agentStore";
import { getRouteChatId } from "../Chat/routeSession";
import sessionApi, { isDraftSessionId } from "../Chat/sessionApi";

export default function TaskConversationRoute({
  children,
}: {
  children: ReactNode;
}) {
  const { pathname } = useLocation();
  const chatId = getRouteChatId(pathname);
  const requiresResolution = !!chatId && !isDraftSessionId(chatId);
  // Bootstrap only. Once mounted, TaskPage owns in-app routing and draft submission.
  const [opened, setOpened] = useState(!requiresResolution);
  const [errorId, setErrorId] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!requiresResolution || !chatId) {
      setOpened(true);
      return;
    }
    if (opened) return;
    let active = true;
    setErrorId(null);
    superExpertPlatformApi
      .getConversationRoute(chatId)
      .then((route) => {
        if (!active) return;
        if (route.conversation_id !== chatId || !route.agent_id?.trim()) {
          throw new Error("Conversation route mismatch");
        }
        // The setter persists the scope used by API headers before chat mounts.
        const store = useAgentStore.getState();
        if (store.selectedAgent !== route.agent_id) {
          sessionApi.reset();
          store.setSelectedAgent(route.agent_id);
          store.setActiveMode("");
        } else {
          store.setSelectedAgent(route.agent_id);
        }
        setOpened(true);
      })
      .catch(() => {
        if (active) setErrorId(chatId);
      });
    return () => {
      active = false;
    };
  }, [chatId, requiresResolution, retry, opened]);
  if (requiresResolution && !opened) {
    return errorId === chatId ? (
      <div role="alert" style={{ padding: 24 }}>
        <p>暂时无法打开这个任务，请确认当前账号有访问权限后重试。</p>
        <button onClick={() => setRetry((value) => value + 1)}>重试</button>
      </div>
    ) : (
      <div role="status" style={{ padding: 24 }}>
        正在打开任务会话…
      </div>
    );
  }
  return <>{children}</>;
}
