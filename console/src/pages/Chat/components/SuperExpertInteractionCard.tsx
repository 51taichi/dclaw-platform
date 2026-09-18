import { FormEvent, useRef, useState } from "react";
import { Check, LoaderCircle, Sparkles } from "lucide-react";
import styles from "./SuperExpertInteractionCard.module.less";

export type InteractionCardStatus =
  | "PENDING"
  | "SUBMITTED"
  | "CANCELLED"
  | "REPLACED"
  | "EXPIRED";

interface InteractionProjectionBase {
  interactionId: string;
  version: number;
  status: InteractionCardStatus;
  inputPolicy: "card_only" | "card_or_text" | "concurrent";
  title: string;
  description: string | null;
  submissionInFlight?: boolean;
  submissionFailed?: boolean;
}

export interface ChoiceInteractionProjection extends InteractionProjectionBase {
  componentType: "single_select" | "multi_select";
  layout: "auto" | "list" | "grid";
  options: Array<{
    id: string | null;
    text: string;
    description: string | null;
    recommended: boolean;
    defaultSelected: boolean;
  }>;
  supplement: {
    enabled: boolean;
    required: boolean;
    label: string;
    placeholder: string;
    maxLength: number;
  };
  minSelections: number;
  maxSelections: number;
  answer: {
    selected: Array<{ id: string | null; text: string }>;
    supplement: string | null;
  } | null;
}

export interface QuestionFormInteractionProjection
  extends InteractionProjectionBase {
  componentType: "question_form";
  items: Array<{
    id: string | null;
    question: string;
    description: string | null;
    placeholder: string;
    required: boolean;
    maxLength: number;
  }>;
  answer: {
    answers: Array<{
      id: string | null;
      question: string;
      value: string | null;
    }>;
  } | null;
}

export type SuperExpertInteractionProjection =
  | ChoiceInteractionProjection
  | QuestionFormInteractionProjection;

export interface ChoiceInteractionSubmission {
  version: number;
  selected: Array<{ id: string | null; text: string }>;
  supplement: string | null;
}

export interface QuestionFormInteractionSubmission {
  version: number;
  answers: Array<{
    id: string | null;
    question: string;
    value: string | null;
  }>;
}

export type InteractionCardSubmission =
  | ChoiceInteractionSubmission
  | QuestionFormInteractionSubmission;

const optionKey = (option: ChoiceInteractionProjection["options"][number]) =>
  option.id ? `id:${option.id}` : `text:${option.text}`;

function initialSelection(projection: ChoiceInteractionProjection) {
  const persisted = projection.answer?.selected;
  if (persisted?.length) {
    return new Set(
      projection.options
        .filter((option) =>
          persisted.some(
            (selected) =>
              (selected.id && selected.id === option.id) ||
              (!selected.id && selected.text === option.text),
          ),
        )
        .map(optionKey),
    );
  }
  return new Set(
    projection.options
      .filter((option) => option.defaultSelected)
      .map(optionKey),
  );
}

function contentColumnSpan(text: string, description: string | null) {
  return `${text}${description || ""}`.replace(/\s/g, "").length > 54
    ? "full"
    : "auto";
}

const responsiveCardSize = {
  width: "720px",
  maxWidth: "100%",
} as const;

function ChoiceInteractionCard({
  projection,
  onSubmit,
}: {
  projection: ChoiceInteractionProjection;
  onSubmit: (submission: InteractionCardSubmission) => Promise<void>;
}) {
  const [selected, setSelected] = useState(() => initialSelection(projection));
  const [supplement, setSupplement] = useState(
    () => projection.answer?.supplement || "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const submittingRef = useRef(false);
  const pending = projection.status === "PENDING";
  const submissionInFlight = projection.submissionInFlight === true;
  const submissionFailed = projection.submissionFailed === true;
  const busy = submitting || submissionInFlight;
  const actionable = pending || submissionInFlight || submissionFailed;

  const toggle = (option: ChoiceInteractionProjection["options"][number]) => {
    if (!pending || submittingRef.current) return;
    const key = optionKey(option);
    setError("");
    setSelected((current) => {
      if (projection.componentType === "single_select") return new Set([key]);
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else if (next.size < projection.maxSelections) next.add(key);
      return next;
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!actionable || busy || submittingRef.current) return;
    if (
      selected.size < projection.minSelections ||
      selected.size > projection.maxSelections
    ) {
      setError(
        projection.componentType === "single_select"
          ? "请选择一项"
          : `请选择 ${projection.minSelections}–${projection.maxSelections} 项`,
      );
      return;
    }
    const normalizedSupplement = supplement.trim();
    if (projection.supplement.required && !normalizedSupplement) {
      setError("请填写补充信息");
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError("");
    try {
      await onSubmit({
        version: projection.version,
        selected: projection.options
          .filter((option) => selected.has(optionKey(option)))
          .map((option) => ({ id: option.id, text: option.text })),
        supplement: normalizedSupplement || null,
      });
    } catch {
      setError("提交失败，请重试");
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <form
      className={styles.card}
      style={responsiveCardSize}
      data-super-expert-interaction-card={projection.interactionId}
      data-status={projection.status.toLowerCase()}
      data-layout={projection.layout}
      onSubmit={submit}
    >
      <fieldset className={styles.options} disabled={!pending || busy}>
        <legend className={styles.srOnly}>
          {projection.componentType === "single_select" ? "单选" : "多选"}
        </legend>
        {projection.options.map((option) => {
          const key = optionKey(option);
          const checked = selected.has(key);
          const atLimit =
            projection.componentType === "multi_select" &&
            !checked &&
            selected.size >= projection.maxSelections;
          return (
            <label
              key={key}
              className={styles.option}
              data-column-span={contentColumnSpan(
                option.text,
                option.description,
              )}
              data-selected={checked}
              data-disabled={atLimit || undefined}
            >
              <input
                type={
                  projection.componentType === "single_select"
                    ? "radio"
                    : "checkbox"
                }
                name={projection.interactionId}
                checked={checked}
                disabled={!pending || busy || atLimit}
                onChange={() => toggle(option)}
              />
              <span className={styles.control} aria-hidden="true">
                {checked ? <Check size={13} strokeWidth={3} /> : null}
              </span>
              <span className={styles.optionContent}>
                <span className={styles.optionTitle}>
                  <span>{option.text}</span>
                  {option.recommended ? (
                    <span className={styles.recommended}>
                      <Sparkles size={12} /> AI 推荐
                    </span>
                  ) : null}
                </span>
                {option.description ? (
                  <span className={styles.optionDescription}>
                    {option.description}
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </fieldset>

      {projection.supplement.enabled ? (
        <label className={styles.supplement}>
          <span>
            {projection.supplement.label}
            {projection.supplement.required ? (
              <span className={styles.required}>必填</span>
            ) : null}
          </span>
          <textarea
            aria-label={projection.supplement.label}
            value={supplement}
            placeholder={projection.supplement.placeholder}
            maxLength={projection.supplement.maxLength}
            disabled={!pending || busy}
            rows={2}
            onChange={(event) => {
              setSupplement(event.target.value);
              setError("");
              event.currentTarget.style.height = "auto";
              event.currentTarget.style.height = `${event.currentTarget.scrollHeight}px`;
            }}
          />
          <small>
            {supplement.length}/{projection.supplement.maxLength}
          </small>
        </label>
      ) : null}

      {error ? (
        <p className={styles.error} role="alert" aria-live="polite">
          {error}
        </p>
      ) : null}
      {actionable ? (
        <footer className={styles.footer}>
          <span className={styles.hint}>
            {submissionInFlight
              ? "正在提交"
              : submissionFailed
              ? "提交结果未送达，请重试"
              : projection.componentType === "multi_select"
              ? `可选 ${projection.minSelections}–${projection.maxSelections} 项`
              : "请选择一项"}
          </span>
          <button type="submit" disabled={busy} aria-busy={busy}>
            {busy ? (
              <LoaderCircle
                className={styles.submitSpinner}
                data-testid="submit-spinner"
                size={16}
                aria-hidden="true"
              />
            ) : null}
            {busy ? "提交中…" : submissionFailed ? "重新提交" : "提交选择"}
          </button>
        </footer>
      ) : null}
    </form>
  );
}

const questionKey = (
  item: QuestionFormInteractionProjection["items"][number],
) => (item.id ? `id:${item.id}` : `question:${item.question}`);

function initialAnswers(projection: QuestionFormInteractionProjection) {
  return projection.items.map((item) => {
    const persisted = projection.answer?.answers.find(
      (answer) =>
        (answer.id && answer.id === item.id) ||
        (!answer.id && answer.question === item.question),
    );
    return persisted?.value || "";
  });
}

function QuestionFormInteractionCard({
  projection,
  onSubmit,
}: {
  projection: QuestionFormInteractionProjection;
  onSubmit: (submission: InteractionCardSubmission) => Promise<void>;
}) {
  const [answers, setAnswers] = useState(() => initialAnswers(projection));
  const [itemErrors, setItemErrors] = useState<Record<number, string>>({});
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const textareas = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const pending = projection.status === "PENDING";
  const submissionInFlight = projection.submissionInFlight === true;
  const submissionFailed = projection.submissionFailed === true;
  const busy = submitting || submissionInFlight;
  const actionable = pending || submissionInFlight || submissionFailed;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!actionable || busy || submittingRef.current) return;
    const normalized = answers.map((value) => value.trim());
    if (pending) {
      const nextErrors: Record<number, string> = {};
      projection.items.forEach((item, index) => {
        if (item.required && !normalized[index]) {
          nextErrors[index] = "请填写此项";
        }
      });
      if (Object.keys(nextErrors).length) {
        setItemErrors(nextErrors);
        const first = Number(Object.keys(nextErrors)[0]);
        textareas.current[questionKey(projection.items[first])]?.focus();
        return;
      }
    }
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError("");
    setItemErrors({});
    try {
      await onSubmit({
        version: projection.version,
        answers: projection.items.map((item, index) => ({
          id: item.id,
          question: item.question,
          value: normalized[index] || null,
        })),
      });
    } catch {
      setSubmitError("提交失败，请重试");
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <form
      className={styles.card}
      style={responsiveCardSize}
      data-super-expert-interaction-card={projection.interactionId}
      data-status={projection.status.toLowerCase()}
      data-component="question_form"
      onSubmit={submit}
    >
      <fieldset className={styles.questionItems} disabled={!pending || busy}>
        <legend className={styles.srOnly}>问答表单</legend>
        {projection.items.map((item, index) => {
          const key = questionKey(item);
          const error = itemErrors[index];
          const errorId = `${projection.interactionId}-question-${index}-error`;
          return (
            <div
              key={key}
              className={styles.questionItem}
              data-testid="question-item"
              data-column-span={contentColumnSpan(
                item.question,
                item.description,
              )}
              data-invalid={Boolean(error) || undefined}
            >
              <label className={styles.questionLabel}>
                <span className={styles.questionTitle}>
                  <span>{item.question}</span>
                  <span
                    className={
                      item.required ? styles.required : styles.optional
                    }
                  >
                    {item.required ? "必填" : "选填"}
                  </span>
                </span>
                {item.description ? (
                  <span className={styles.questionDescription}>
                    {item.description}
                  </span>
                ) : null}
                <textarea
                  ref={(element) => {
                    textareas.current[key] = element;
                  }}
                  aria-label={item.question}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? errorId : undefined}
                  value={answers[index] || ""}
                  placeholder={item.placeholder}
                  maxLength={item.maxLength}
                  disabled={!pending || busy}
                  rows={2}
                  onChange={(event) => {
                    const value = event.target.value;
                    setAnswers((current) =>
                      current.map((answer, answerIndex) =>
                        answerIndex === index ? value : answer,
                      ),
                    );
                    setItemErrors((current) => {
                      if (!current[index]) return current;
                      const next = { ...current };
                      delete next[index];
                      return next;
                    });
                    setSubmitError("");
                    event.currentTarget.style.height = "auto";
                    event.currentTarget.style.height = `${event.currentTarget.scrollHeight}px`;
                  }}
                />
              </label>
              <div className={styles.questionMeta}>
                {error ? (
                  <span id={errorId} className={styles.itemError} role="alert">
                    {error}
                  </span>
                ) : (
                  <span />
                )}
                <small>
                  {(answers[index] || "").length}/{item.maxLength}
                </small>
              </div>
            </div>
          );
        })}
      </fieldset>

      {submitError ? (
        <p className={styles.error} role="alert" aria-live="polite">
          {submitError}
        </p>
      ) : null}
      {actionable ? (
        <footer className={styles.footer}>
          <span className={styles.hint}>
            {submissionInFlight
              ? "正在提交"
              : submissionFailed
              ? "提交结果未送达，请重试"
              : `请完成 ${
                  projection.items.filter((item) => item.required).length
                } 个必填项`}
          </span>
          <button type="submit" disabled={busy} aria-busy={busy}>
            {busy ? (
              <LoaderCircle
                className={styles.submitSpinner}
                data-testid="submit-spinner"
                size={16}
                aria-hidden="true"
              />
            ) : null}
            {busy ? "提交中…" : submissionFailed ? "重新提交" : "提交回答"}
          </button>
        </footer>
      ) : null}
    </form>
  );
}

export function SuperExpertInteractionCard({
  projection,
  onSubmit,
}: {
  projection: SuperExpertInteractionProjection;
  onSubmit: (submission: InteractionCardSubmission) => Promise<void>;
}) {
  return projection.componentType === "question_form" ? (
    <QuestionFormInteractionCard
      key={`${projection.interactionId}:${projection.version}`}
      projection={projection}
      onSubmit={onSubmit}
    />
  ) : (
    <ChoiceInteractionCard
      key={`${projection.interactionId}:${projection.version}`}
      projection={projection}
      onSubmit={onSubmit}
    />
  );
}
