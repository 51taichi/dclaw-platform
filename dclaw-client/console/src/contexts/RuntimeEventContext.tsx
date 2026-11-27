import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  type RuntimeEvent,
  streamRuntimeEvents,
} from "../api/modules/runtimeEvents";

interface RuntimeEventContextValue {
  activeSessionId: string | null;
  setActiveSessionId: (sessionId: string | null) => void;
  connected: boolean;
  fallbackPolling: boolean;
  lastEventId: string | null;
  events: RuntimeEvent[];
  clearEvents: () => void;
}

const RuntimeEventContext = createContext<RuntimeEventContextValue | undefined>(
  undefined,
);

function isPageVisible(): boolean {
  if (typeof document === "undefined") return true;
  return document.visibilityState !== "hidden";
}

export function RuntimeEventProvider({ children }: { children: ReactNode }) {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [fallbackPolling, setFallbackPolling] = useState(false);
  const [lastEventId, setLastEventId] = useState<string | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [pageVisible, setPageVisible] = useState(isPageVisible);
  const lastEventIdsRef = useRef<Record<string, string>>({});

  useEffect(() => {
    const handleVisibilityChange = () => {
      setPageVisible(isPageVisible());
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!activeSessionId || !pageVisible) {
      setConnected(false);
      return;
    }

    const controller = new AbortController();
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const sessionId = activeSessionId;
    setConnected(false);
    setFallbackPolling(false);

    const scheduleReconnect = () => {
      if (disposed || controller.signal.aborted) return;
      setConnected(false);
      setFallbackPolling(true);
      reconnectTimer = setTimeout(connect, 1_000);
    };

    const connect = () => {
      if (disposed || controller.signal.aborted) return;
      const sinceId = lastEventIdsRef.current[sessionId] ?? null;
      void streamRuntimeEvents({
        sessionId,
        sinceId,
        signal: controller.signal,
        onOpen: () => {
          if (!disposed) {
            setConnected(true);
            setFallbackPolling(false);
          }
        },
        onEvent: (event) => {
          if (disposed) return;
          if (event.id) {
            lastEventIdsRef.current[sessionId] = event.id;
            setLastEventId(event.id);
          }
          setEvents((current) => [...current.slice(-99), event]);
        },
      })
        .then(() => {
          scheduleReconnect();
        })
        .catch((error) => {
          if (controller.signal.aborted || disposed) return;
          console.warn(
            "Runtime event stream unavailable, falling back to polling",
            error,
          );
          scheduleReconnect();
        });
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      controller.abort();
    };
  }, [activeSessionId, pageVisible]);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  const value = useMemo<RuntimeEventContextValue>(
    () => ({
      activeSessionId,
      setActiveSessionId,
      connected,
      fallbackPolling,
      lastEventId,
      events,
      clearEvents,
    }),
    [
      activeSessionId,
      connected,
      fallbackPolling,
      lastEventId,
      events,
      clearEvents,
    ],
  );

  return (
    <RuntimeEventContext.Provider value={value}>
      {children}
    </RuntimeEventContext.Provider>
  );
}

export function useRuntimeEvents(): RuntimeEventContextValue {
  const context = useContext(RuntimeEventContext);
  if (!context) {
    throw new Error(
      "useRuntimeEvents must be used within RuntimeEventProvider",
    );
  }
  return context;
}
