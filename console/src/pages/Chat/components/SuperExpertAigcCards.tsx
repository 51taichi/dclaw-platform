import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { superExpertPlatformApi } from "../../../api/modules/superExpertPlatform";
import { useRuntimeEvents } from "../../../contexts/RuntimeEventContext";
import { buildAigcTaskRoute } from "../routeSession";
import {
  SuperExpertAigcTaskCard,
  type SuperExpertAigcTaskCardProjection,
  projectSuperExpertAigcCards,
} from "./SuperExpertAigcTaskCard";
import styles from "./SuperExpertAigcTaskCard.module.less";

const ACTIVE_POLL_INTERVAL_MS = 1_200;
const FALLBACK_POLL_INTERVAL_MS = 5_000;

function cardIntroductionKey(conversationId: string): string {
  return `dclaw:aigc-card-introduced:${conversationId}`;
}

function mergeCards(
  snapshotCards: SuperExpertAigcTaskCardProjection[],
  liveCards: SuperExpertAigcTaskCardProjection[],
): SuperExpertAigcTaskCardProjection[] {
  const merged = new Map(
    snapshotCards.map((card) => [card.materialTaskId, card]),
  );
  for (const card of liveCards) {
    const existing = merged.get(card.materialTaskId);
    merged.set(card.materialTaskId, {
      ...existing,
      ...card,
      cardId: card.cardId || existing?.cardId || card.materialTaskId,
      title:
        card.title === "AIGC 素材制作任务" && existing?.title
          ? existing.title
          : card.title,
      instruction: card.instruction || existing?.instruction,
      installationId: card.installationId || existing?.installationId,
      binding: {
        ...existing?.binding,
        ...card.binding,
      },
    });
  }
  return [...merged.values()];
}

export function SuperExpertAigcCards({
  conversationId,
  watchForNewCards = false,
}: {
  conversationId: string;
  watchForNewCards?: boolean;
}) {
  const navigate = useNavigate();
  const listId = useId();
  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem("dclaw:aigc-card-shelf:expanded") === "true";
    } catch {
      return false;
    }
  });
  const toggleExpanded = () => {
    const next = !expanded;
    setExpanded(next);
    try {
      localStorage.setItem("dclaw:aigc-card-shelf:expanded", String(next));
    } catch {
      /* Storage restrictions must not prevent changing the layout. */
    }
  };
  const lifetime = useRef<{ active: boolean }>({ active: false });
  useEffect(() => {
    const current = { active: true };
    lifetime.current = current;
    return () => {
      current.active = false;
    };
  }, [conversationId]);
  const { events, fallbackPolling } = useRuntimeEvents();
  const conversationEvents = useMemo(
    () =>
      events.filter((event) => {
        if (event.type !== "super_expert_event") return false;
        const envelope = event.payload?.envelope;
        return (
          !!envelope &&
          typeof envelope === "object" &&
          String(
            (envelope as Record<string, unknown>).conversation_id || "",
          ) === conversationId
        );
      }),
    [conversationId, events],
  );
  const liveCards = useMemo(
    () => projectSuperExpertAigcCards(conversationEvents),
    [conversationEvents],
  );
  const lastEvent = [...conversationEvents]
    .reverse()
    .find((event) => event.type === "super_expert_event")?.id;
  const [snapshot, setSnapshot] = useState<{
    conversationId: string;
    cards: SuperExpertAigcTaskCardProjection[];
  } | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [introducedTaskId, setIntroducedTaskId] = useState<string | null>(null);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState !== "hidden") setRetry((value) => value + 1);
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  useEffect(() => {
    let active = true;
    setError(false);
    superExpertPlatformApi
      .listCards(conversationId)
      .then(({ cards }) => {
        if (!active) return;
        setSnapshot({
          conversationId,
          cards: cards.map((card) => ({
            cardId: card.material_task_id,
            materialTaskId: card.material_task_id,
            title: card.title,
            instruction: card.instruction,
            status: card.status as SuperExpertAigcTaskCardProjection["status"],
            installationId: card.binding.installation_id,
            binding: { ...card.binding },
          })),
        });
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [conversationId, lastEvent, retry]);
  useEffect(() => {
    if (!watchForNewCards && !fallbackPolling) return;
    const interval = window.setInterval(
      () => {
        if (document.visibilityState !== "hidden") {
          setRetry((value) => value + 1);
        }
      },
      watchForNewCards ? ACTIVE_POLL_INTERVAL_MS : FALLBACK_POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(interval);
  }, [fallbackPolling, watchForNewCards]);
  const snapshotCards =
    snapshot?.conversationId === conversationId ? snapshot.cards : [];
  const cards = useMemo(
    () => mergeCards(snapshotCards, liveCards),
    [liveCards, snapshotCards],
  );
  const firstCardId = cards[0]?.materialTaskId;
  useEffect(() => {
    if (!firstCardId) return;
    const key = cardIntroductionKey(conversationId);
    try {
      if (localStorage.getItem(key) === "true") return;
      localStorage.setItem(key, "true");
    } catch {
      /* The current mount still provides one introduction without storage. */
    }
    setExpanded(true);
    setIntroducedTaskId(firstCardId);
    const timer = window.setTimeout(() => setIntroducedTaskId(null), 6_000);
    return () => window.clearTimeout(timer);
  }, [conversationId, firstCardId]);
  if (!cards.length && !error) return null;
  return (
    <section className={styles.shelf} aria-label="本会话 AIGC 素材">
      <div className={styles.shelfHeading}>
        <span>
          素材任务 <span className={styles.count}>{cards.length}</span>
        </span>
        {introducedTaskId ? (
          <span className={styles.introHint} role="status" aria-live="polite">
            <Sparkles size={13} />
            新素材任务已创建，点击卡片开始制作
          </span>
        ) : null}
        <button
          type="button"
          className={styles.toggle}
          aria-label={expanded ? "收起素材任务" : "展开素材任务"}
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={toggleExpanded}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          {expanded ? "收起" : "展开"}
        </button>
      </div>
      {error && (
        <p role="alert">
          素材入口加载失败。
          <button onClick={() => setRetry((value) => value + 1)}>重试</button>
        </p>
      )}
      <div
        className={styles.list}
        id={listId}
        data-expanded={expanded}
        tabIndex={0}
        role="region"
        aria-label="横向滚动素材任务"
      >
        {cards.map((projection) => (
          <SuperExpertAigcTaskCard
            key={projection.materialTaskId}
            projection={projection}
            compact={!expanded}
            emphasized={introducedTaskId === projection.materialTaskId}
            onCommand={async (_, materialTaskId) => {
              setIntroducedTaskId(null);
              const currentLifetime = lifetime.current;
              const current = await superExpertPlatformApi.getTask(
                materialTaskId,
              );
              if (!currentLifetime.active) return;
              if (
                ["WAITING_TO_START", "PAUSED", "REVISION_REQUIRED"].includes(
                  current.status,
                )
              ) {
                const eventId = crypto.randomUUID();
                await superExpertPlatformApi.command("aigc.task.resume", {
                  installation_id: current.binding.installation_id,
                  contract_version: "1",
                  idempotency_key: eventId,
                  arguments: { event_id: eventId, binding: current.binding },
                });
              }
              if (!currentLifetime.active) return;
              navigate(buildAigcTaskRoute(materialTaskId));
            }}
          />
        ))}
      </div>
    </section>
  );
}
