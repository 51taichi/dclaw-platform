import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { consoleApi, type PushMessage } from "../../api/modules/console";
import { useApprovalContext } from "../../contexts/ApprovalContext";
import { useRuntimeEvents } from "../../contexts/RuntimeEventContext";
import { getConsolePollDelay } from "./polling";
import styles from "./index.module.less";

const AUTO_DISMISS_MS = 8000;
const MAX_SEEN_IDS = 500;
const MAX_VISIBLE_BUBBLES = 4;
const MAX_NEW_PER_POLL = 2;
const TITLE_BLINK_PREFIX = "\u2022 ";
const SESSION_REFRESH_EVENT_TYPES = new Set([
  "task.progress",
  "task.completed",
  "task.failed",
  "task.cancelled",
  "approval.created",
  "approval.resolved",
  "skill.install.updated",
  "expert_team.run.updated",
  "aigc.job.updated",
]);

type PushMessagesResponse = Awaited<
  ReturnType<typeof consoleApi.getPushMessages>
>;

interface BubbleItem extends PushMessage {
  dismissAt: number;
}

export default function ConsolePollService() {
  const [items, setItems] = useState<BubbleItem[]>([]);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollInFlightRef = useRef(false);
  const eventRefreshInFlightRef = useRef(false);
  const eventRefreshPendingSessionRef = useRef<string | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const seenRuntimeEventIdsRef = useRef<Set<string>>(new Set());
  const prevApprovalsRef = useRef("");
  const originalTitleRef = useRef(document.title);
  const blinkRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { setApprovals } = useApprovalContext();
  const { activeSessionId, events: runtimeEvents } = useRuntimeEvents();

  const dismiss = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  useEffect(() => {
    originalTitleRef.current = document.title;
  }, []);

  const applyPushMessages = useCallback(
    (res?: PushMessagesResponse) => {
      // Update pending approvals only when they actually change,
      // to avoid triggering unnecessary re-renders in Chat component
      // every polling cycle.
      if (res?.pending_approvals) {
        const serialized = JSON.stringify(res.pending_approvals);
        if (serialized !== prevApprovalsRef.current) {
          prevApprovalsRef.current = serialized;
          setApprovals(res.pending_approvals);
        }
      }

      if (!res?.messages?.length) return;
      const seen = seenIdsRef.current;
      if (seen.size > MAX_SEEN_IDS) seen.clear();
      const newItems: BubbleItem[] = [];
      const now = Date.now();
      for (const m of res.messages) {
        if (seen.has(m.id)) continue;
        seen.add(m.id);
        newItems.push({ ...m, dismissAt: now + AUTO_DISMISS_MS });
      }
      if (newItems.length === 0) return;
      const toAdd = newItems.slice(-MAX_NEW_PER_POLL);
      setItems((prev) => {
        const merged = [...prev, ...toAdd];
        return merged.slice(-MAX_VISIBLE_BUBBLES);
      });
    },
    [setApprovals],
  );

  const refreshSessionPushMessages = useCallback(
    (sessionId: string) => {
      if (eventRefreshInFlightRef.current) {
        eventRefreshPendingSessionRef.current = sessionId;
        return;
      }
      eventRefreshInFlightRef.current = true;
      void consoleApi
        .getPushMessages(sessionId)
        .then(applyPushMessages)
        .catch(() => {})
        .finally(() => {
          eventRefreshInFlightRef.current = false;
          const pendingSessionId = eventRefreshPendingSessionRef.current;
          eventRefreshPendingSessionRef.current = null;
          if (pendingSessionId) {
            refreshSessionPushMessages(pendingSessionId);
          }
        });
    },
    [applyPushMessages],
  );

  useEffect(() => {
    let stopped = false;

    const scheduleNext = () => {
      if (stopped) return;
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = setTimeout(
        tick,
        getConsolePollDelay(document.visibilityState),
      );
    };

    const tick = () => {
      if (stopped) return;
      if (pollInFlightRef.current) {
        scheduleNext();
        return;
      }
      pollInFlightRef.current = true;
      void consoleApi
        .getPushMessages()
        .then(applyPushMessages)
        .catch(() => {})
        .finally(() => {
          pollInFlightRef.current = false;
          scheduleNext();
        });
    };

    tick();
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        tick();
      } else {
        scheduleNext();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [applyPushMessages]);

  useEffect(() => {
    if (items.length === 0) return;
    const t = setInterval(() => {
      const now = Date.now();
      setItems((prev) => {
        const next = prev.filter((i) => i.dismissAt > now);
        return next.length === prev.length ? prev : next;
      });
    }, 500);
    return () => clearInterval(t);
  }, [items.length]);

  useEffect(() => {
    if (!runtimeEvents.length) return;
    const seen = seenRuntimeEventIdsRef.current;
    if (seen.size > MAX_SEEN_IDS) seen.clear();
    const now = Date.now();
    const newItems: BubbleItem[] = [];
    let shouldRefreshActiveSession = false;
    for (const event of runtimeEvents) {
      if (!event.id || seen.has(event.id)) continue;
      seen.add(event.id);
      const targetsActiveSession =
        activeSessionId &&
        (!event.session_id || event.session_id === activeSessionId);
      if (targetsActiveSession && SESSION_REFRESH_EVENT_TYPES.has(event.type)) {
        shouldRefreshActiveSession = true;
      }
      if (event.type === "task.progress" && event.message) {
        newItems.push({
          id: `runtime:${event.id}`,
          text: event.message,
          dismissAt: now + AUTO_DISMISS_MS,
        });
      }
    }
    if (shouldRefreshActiveSession && activeSessionId) {
      refreshSessionPushMessages(activeSessionId);
    }
    if (newItems.length) {
      setItems((prev) => {
        const merged = [...prev, ...newItems.slice(-MAX_NEW_PER_POLL)];
        return merged.slice(-MAX_VISIBLE_BUBBLES);
      });
    }
  }, [activeSessionId, refreshSessionPushMessages, runtimeEvents]);

  useEffect(() => {
    if (items.length === 0 || !document.hidden || blinkRef.current) return;
    const original = originalTitleRef.current;
    let showPrefix = true;
    blinkRef.current = setInterval(() => {
      document.title = showPrefix
        ? `${TITLE_BLINK_PREFIX}${original}`
        : original;
      showPrefix = !showPrefix;
    }, 800);
    return () => {
      if (blinkRef.current) {
        clearInterval(blinkRef.current);
        blinkRef.current = null;
      }
      document.title = original;
    };
  }, [items.length]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        if (blinkRef.current) {
          clearInterval(blinkRef.current);
          blinkRef.current = null;
        }
        document.title = originalTitleRef.current;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className={styles.wrap} role="region" aria-label="Cron messages">
      {items.map((item) => (
        <div key={item.id} className={styles.bubble}>
          <MessageCircle size={18} className={styles.icon} aria-hidden />
          <p className={styles.text} title={item.text}>
            {item.text}
          </p>
          <button
            type="button"
            className={styles.close}
            onClick={() => dismiss(item.id)}
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
