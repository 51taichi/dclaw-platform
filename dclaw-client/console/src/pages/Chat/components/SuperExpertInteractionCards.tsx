import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  superExpertPlatformApi,
  type InteractionCardRecord,
} from "../../../api/modules/superExpertPlatform";
import { useRuntimeEvents } from "../../../contexts/RuntimeEventContext";
import {
  SuperExpertInteractionCard,
  type InteractionCardSubmission,
  type SuperExpertInteractionProjection,
} from "./SuperExpertInteractionCard";

function projectInteraction(
  record: InteractionCardRecord,
): SuperExpertInteractionProjection {
  if (record.component_type === "question_form") {
    return {
      interactionId: record.interaction_id,
      version: record.version,
      status: record.status,
      inputPolicy: record.input_policy,
      componentType: record.component_type,
      title: record.card.title,
      description: record.card.description,
      items: record.card.items.map((item) => ({
        id: item.id,
        question: item.question,
        description: item.description,
        placeholder: item.placeholder,
        required: item.required,
        maxLength: item.max_length,
      })),
      answer: record.answer,
    };
  }
  const maximum =
    record.component_type === "single_select"
      ? 1
      : record.card.max_selections || record.card.options.length;
  return {
    interactionId: record.interaction_id,
    version: record.version,
    status: record.status,
    inputPolicy: record.input_policy,
    componentType: record.component_type,
    title: record.card.title,
    description: record.card.description,
    layout: record.card.layout,
    options: record.card.options.map((option) => ({
      id: option.id,
      text: option.text,
      description: option.description,
      recommended: option.recommended,
      defaultSelected: option.default_selected,
      actionUrl: option.action_url ?? null,
      autoSubmitOnDesktop: option.auto_submit_on_desktop === true,
    })),
    supplement: {
      enabled: record.card.supplement.enabled,
      answerMode: record.card.supplement.answer_mode ?? "note",
      required: record.card.supplement.required,
      label: record.card.supplement.label,
      placeholder: record.card.supplement.placeholder,
      maxLength: record.card.supplement.max_length,
    },
    minSelections:
      record.component_type === "single_select"
        ? 1
        : record.card.min_selections ?? 1,
    maxSelections: maximum,
    answer: record.answer,
  };
}

function mergeRecords(
  snapshot: InteractionCardRecord[],
  live: InteractionCardRecord[],
) {
  const merged = new Map<string, InteractionCardRecord>();
  for (const record of [...snapshot, ...live]) {
    const current = merged.get(record.interaction_id);
    if (!current || record.version > current.version) {
      merged.set(record.interaction_id, record);
    }
  }
  return [...merged.values()].sort((left, right) =>
    left.created_at.localeCompare(right.created_at),
  );
}

export function SuperExpertInteractionCards({
  conversationId,
  responseRevision = 0,
  onBlockingChange,
  onSubmitAsUserInput,
  inline = false,
}: {
  conversationId: string;
  responseRevision?: number;
  onBlockingChange?: (blocked: boolean) => void;
  onSubmitAsUserInput?: (text: string) => void;
  inline?: boolean;
}) {
  const { events } = useRuntimeEvents();
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;
  const [snapshotState, setSnapshotState] = useState<{
    conversationId: string;
    records: InteractionCardRecord[];
  }>(() => ({ conversationId, records: [] }));
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const [hostRevision, setHostRevision] = useState(0);
  const [submissionState, setSubmissionState] = useState<{
    conversationId: string;
    active: Set<string>;
    failed: Set<string>;
  }>(() => ({ conversationId, active: new Set(), failed: new Set() }));
  const operationKeys = useRef(new Map<string, string>());
  const pendingSubmissions = useRef(
    new Map<
      string,
      {
        conversationId: string;
        operationIdentity: string;
        submission: InteractionCardSubmission;
      }
    >(),
  );
  const deferredUserInputs = useRef(new Map<string, string[]>());
  const snapshot = useMemo(
    () =>
      snapshotState.conversationId === conversationId
        ? snapshotState.records
        : [],
    [conversationId, snapshotState],
  );
  const activeSubmissions = useMemo(
    () =>
      submissionState.conversationId === conversationId
        ? submissionState.active
        : new Set<string>(),
    [conversationId, submissionState],
  );
  const failedSubmissions = useMemo(
    () =>
      submissionState.conversationId === conversationId
        ? submissionState.failed
        : new Set<string>(),
    [conversationId, submissionState],
  );

  useLayoutEffect(() => {
    if (!inline) return;
    const refreshHosts = () => setHostRevision((value) => value + 1);
    refreshHosts();
    const observer = new MutationObserver(refreshHosts);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", refreshHosts);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", refreshHosts);
    };
  }, [conversationId, inline]);

  const liveRecords = useMemo(() => {
    const records: InteractionCardRecord[] = [];
    for (const event of events) {
      if (event.type !== "super_expert_interaction") continue;
      const envelope = event.payload?.envelope;
      if (!envelope || typeof envelope !== "object") continue;
      const value = envelope as Record<string, unknown>;
      if (String(value.conversation_id || "") !== conversationId) continue;
      const interaction = value.interaction;
      if (interaction && typeof interaction === "object") {
        records.push(interaction as InteractionCardRecord);
      }
    }
    return records;
  }, [conversationId, events]);

  const lastLiveVersion = liveRecords
    .map((record) => `${record.interaction_id}:${record.version}`)
    .join("|");
  const interactionEventRevision = events
    .filter((event) => {
      if (event.type !== "super_expert_interaction") return false;
      const envelope = event.payload?.envelope;
      return (
        envelope &&
        typeof envelope === "object" &&
        String((envelope as Record<string, unknown>).conversation_id || "") ===
          conversationId
      );
    })
    .map((event) => event.id)
    .join("|");

  useEffect(() => {
    let active = true;
    setLoadError(false);
    superExpertPlatformApi
      .listInteractions(conversationId)
      .then(({ interactions }) => {
        if (active && conversationIdRef.current === conversationId) {
          setSnapshotState({ conversationId, records: interactions });
        }
      })
      .catch(() => {
        if (active) setLoadError(true);
      });
    return () => {
      active = false;
    };
  }, [
    conversationId,
    interactionEventRevision,
    lastLiveVersion,
    reload,
    responseRevision,
  ]);

  const records = useMemo(
    () => mergeRecords(snapshot, liveRecords),
    [liveRecords, snapshot],
  );
  const projections = useMemo(
    () =>
      records.map((record) => ({
        ...projectInteraction(record),
        submissionInFlight: activeSubmissions.has(record.interaction_id),
        submissionFailed: failedSubmissions.has(record.interaction_id),
      })),
    [activeSubmissions, failedSubmissions, records],
  );
  const blocked = projections.some(
    (card) =>
      card.inputPolicy === "card_only" &&
      (card.status === "PENDING" ||
        card.submissionInFlight === true ||
        card.submissionFailed === true),
  );

  useEffect(() => {
    onBlockingChange?.(blocked);
  }, [blocked, onBlockingChange]);
  useEffect(() => () => onBlockingChange?.(false), [onBlockingChange]);
  useEffect(() => {
    if (!onSubmitAsUserInput) return;
    const pending = deferredUserInputs.current.get(conversationId);
    if (!pending?.length) return;
    deferredUserInputs.current.delete(conversationId);
    for (const text of pending) onSubmitAsUserInput(text);
  }, [conversationId, onSubmitAsUserInput]);

  const submit = async (
    projection: SuperExpertInteractionProjection,
    submission: InteractionCardSubmission,
  ) => {
    const submitConversationId = conversationId;
    const remembered = pendingSubmissions.current.get(projection.interactionId);
    const effectiveSubmission =
      remembered?.conversationId === submitConversationId
        ? remembered.submission
        : submission;
    const operationIdentity = `${projection.interactionId}:${effectiveSubmission.version}`;
    pendingSubmissions.current.set(projection.interactionId, {
      conversationId: submitConversationId,
      operationIdentity,
      submission: effectiveSubmission,
    });
    setSubmissionState((current) => {
      const active =
        current.conversationId === submitConversationId
          ? new Set(current.active)
          : new Set<string>();
      active.add(projection.interactionId);
      const failed =
        current.conversationId === submitConversationId
          ? new Set(current.failed)
          : new Set<string>();
      failed.delete(projection.interactionId);
      return { conversationId: submitConversationId, active, failed };
    });
    let idempotencyKey = operationKeys.current.get(operationIdentity);
    if (!idempotencyKey) {
      idempotencyKey =
        globalThis.crypto?.randomUUID?.() ||
        `interaction-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      operationKeys.current.set(operationIdentity, idempotencyKey);
    }
    try {
      const result = await superExpertPlatformApi.submitInteraction(
        projection.interactionId,
        "answers" in effectiveSubmission
          ? {
              version: effectiveSubmission.version,
              answers: effectiveSubmission.answers.map((answer) => ({
                ...(answer.id
                  ? { id: answer.id }
                  : { question: answer.question }),
                value: answer.value,
              })),
              idempotency_key: idempotencyKey,
            }
          : {
              version: effectiveSubmission.version,
              selected: effectiveSubmission.selected.map((option) => ({
                ...(option.id ? { id: option.id } : {}),
                text: option.text,
              })),
              supplement: effectiveSubmission.supplement,
              idempotency_key: idempotencyKey,
            },
      );
      operationKeys.current.delete(operationIdentity);
      pendingSubmissions.current.delete(projection.interactionId);
      if (conversationIdRef.current !== submitConversationId) {
        deferredUserInputs.current.set(submitConversationId, [
          ...(deferredUserInputs.current.get(submitConversationId) || []),
          result.user_input,
        ]);
        return;
      }
      setSnapshotState((current) => ({
        conversationId: submitConversationId,
        records: mergeRecords(
          current.conversationId === submitConversationId
            ? current.records
            : [],
          [result.interaction],
        ),
      }));
      onSubmitAsUserInput?.(result.user_input);
    } catch (error) {
      if (conversationIdRef.current === submitConversationId) {
        setSubmissionState((current) => {
          if (current.conversationId !== submitConversationId) return current;
          const failed = new Set(current.failed);
          failed.add(projection.interactionId);
          return { ...current, failed };
        });
      }
      throw error;
    } finally {
      setSubmissionState((current) => {
        if (current.conversationId !== submitConversationId) return current;
        const active = new Set(current.active);
        active.delete(projection.interactionId);
        return { ...current, active };
      });
    }
  };

  const renderSection = (
    cards: SuperExpertInteractionProjection[],
    showLoadError: boolean,
  ) => (
    <section aria-label="基础交互">
      {showLoadError ? (
        <p role="alert">
          交互卡片加载失败。
          <button type="button" onClick={() => setReload((value) => value + 1)}>
            重试
          </button>
        </p>
      ) : null}
      {cards.map((projection) => (
        <SuperExpertInteractionCard
          key={projection.interactionId}
          projection={projection}
          onSubmit={(submission) => submit(projection, submission)}
        />
      ))}
    </section>
  );

  if (!projections.length && !loadError) return null;
  if (!inline) return renderSection(projections, loadError);

  void hostRevision;
  const exactHosts = new Map<string, HTMLElement>();
  for (const slot of document.querySelectorAll<HTMLElement>(
    "[data-super-expert-interaction-slot]",
  )) {
    const interactionId = slot.dataset.superExpertInteractionSlot;
    if (interactionId) exactHosts.set(interactionId, slot);
  }
  const fallbackHost = Array.from(
    document.querySelectorAll<HTMLElement>(
      "[data-super-expert-interaction-fallback-slot]",
    ),
  ).reduce<HTMLElement | null>((candidate, slot) => {
    if (!candidate) return slot;
    return slot.getBoundingClientRect().top >
      candidate.getBoundingClientRect().top
      ? slot
      : candidate;
  }, null);
  const groups = new Map<HTMLElement, SuperExpertInteractionProjection[]>();
  for (const projection of projections) {
    const exactHost = exactHosts.get(projection.interactionId);
    const responseBottomHost = exactHost
      ?.closest<HTMLElement>("[data-runtime-progress-card]")
      ?.querySelector<HTMLElement>(
        "[data-super-expert-interaction-fallback-slot]",
      );
    const host =
      responseBottomHost ||
      exactHost ||
      (projection.status === "PENDING" ? fallbackHost : null);
    if (!host) continue;
    groups.set(host, [...(groups.get(host) || []), projection]);
  }
  if (!groups.size && loadError && fallbackHost) {
    groups.set(fallbackHost, []);
  }
  let errorRendered = false;
  return (
    <>
      {Array.from(groups.entries()).map(([host, cards]) => {
        const showLoadError = loadError && !errorRendered;
        errorRendered ||= showLoadError;
        return createPortal(
          renderSection(cards, showLoadError),
          host,
          cards[0]?.interactionId || "interaction-load-error",
        );
      })}
    </>
  );
}

export function InlineSuperExpertInteractionCards({
  conversationId,
  responseRevision = 0,
  onBlockingChange,
  onSubmitAsUserInput,
}: {
  conversationId: string;
  responseRevision?: number;
  onBlockingChange?: (blocked: boolean) => void;
  onSubmitAsUserInput?: (text: string) => void;
}) {
  return (
    <SuperExpertInteractionCards
      conversationId={conversationId}
      responseRevision={responseRevision}
      onBlockingChange={onBlockingChange}
      onSubmitAsUserInput={onSubmitAsUserInput}
      inline
    />
  );
}
