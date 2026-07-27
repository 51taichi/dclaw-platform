import React, { useEffect, useMemo } from "react";
import { useLocation } from "react-router-dom";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { DRAFT_SESSION_ID } from "../../sessionApi";
import { getRouteChatId } from "../../routeSession";

/**
 * URL chatId → context currentSessionId (one direction of bidirectional sync).
 *
 * Only reacts to URL or session list changes. currentSessionId is read via ref
 * to avoid triggering the effect when the context changes from the other direction
 * (context → URL via onSessionSelected), which would cause circular re-loads.
 */
const ChatSessionInitializer: React.FC = () => {
  const location = useLocation();
  const chatId = useMemo(
    () => getRouteChatId(location.pathname),
    [location.pathname],
  );

  const { currentSessionId, setCurrentSessionId } =
    useChatAnywhereSessionsState();

  useEffect(() => {
    // If URL has a specific chat ID, we MUST enforce it in the library context.
    if (chatId) {
      if (currentSessionId !== chatId) {
        setCurrentSessionId(chatId);
      }
    } else {
      // If we are on a task or claw draft root without a specific ID, clear currentSessionId
      // so the chat component starts from draft mode. The first submitted
      // message will create the real backend chat.
      if (
        currentSessionId !== undefined &&
        currentSessionId !== DRAFT_SESSION_ID
      ) {
        console.log("[ChatSessionInitializer] clearing current session id");
        setCurrentSessionId(undefined);
      }
    }
  }, [chatId, currentSessionId, setCurrentSessionId]);

  return null;
};

export default ChatSessionInitializer;
