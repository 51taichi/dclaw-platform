import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimeEvent } from "../../../api/modules/runtimeEvents";
import {
  InlineSuperExpertInteractionCards,
  SuperExpertInteractionCards,
} from "./SuperExpertInteractionCards";

const listInteractions = vi.hoisted(() => vi.fn());
const submitInteraction = vi.hoisted(() => vi.fn());
const runtimeEvents = vi.hoisted(() => ({ current: [] as RuntimeEvent[] }));

vi.mock("../../../api/modules/superExpertPlatform", () => ({
  superExpertPlatformApi: { listInteractions, submitInteraction },
}));
vi.mock("../../../contexts/RuntimeEventContext", () => ({
  useRuntimeEvents: () => ({ events: runtimeEvents.current }),
}));

function record(version = 1, status = "PENDING") {
  return {
    interaction_id: "interaction-1",
    task_key: "pick",
    interaction_revision: 1,
    component_type: "single_select",
    input_policy: "card_only",
    status,
    version,
    binding: {
      installation_id: "installation-1",
      conversation_id: "conversation-1",
      agent_task_id: "task-1",
    },
    card: {
      title: "请选择",
      description: null,
      options: [
        {
          id: "a",
          text: "甲",
          description: null,
          recommended: false,
          default_selected: false,
        },
        {
          id: null,
          text: "乙",
          description: null,
          recommended: false,
          default_selected: false,
        },
      ],
      supplement: {
        enabled: false,
        required: false,
        label: "补充信息",
        placeholder: "补充",
        max_length: 2000,
      },
      layout: "auto",
    },
    answer:
      status === "SUBMITTED"
        ? { selected: [{ id: "a", text: "甲" }], supplement: null }
        : null,
    expires_at: null,
    created_at: "2026-09-17T00:00:00Z",
    updated_at: "2026-09-17T00:00:00Z",
  };
}

function questionRecord(version = 1, status = "PENDING") {
  return {
    interaction_id: "interaction-question-1",
    task_key: "business-context",
    interaction_revision: 1,
    component_type: "question_form",
    input_policy: "card_only",
    status,
    version,
    binding: {
      installation_id: "installation-1",
      conversation_id: "conversation-1",
      agent_task_id: "task-question-1",
    },
    card: {
      title: "请补充以下信息",
      description: null,
      items: [
        {
          id: "scope",
          question: "服务范围？",
          description: null,
          placeholder: "请填写服务范围",
          required: true,
          max_length: 20,
        },
        {
          id: null,
          question: "其他情况？",
          description: null,
          placeholder: "选填",
          required: false,
          max_length: 50,
        },
      ],
    },
    answer:
      status === "SUBMITTED"
        ? {
            answers: [
              { id: "scope", question: "服务范围？", value: "空调维修" },
              { id: null, question: "其他情况？", value: null },
            ],
          }
        : null,
    expires_at: null,
    created_at: "2026-09-17T00:00:00Z",
    updated_at: "2026-09-17T00:00:00Z",
  };
}

describe("SuperExpertInteractionCards", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    runtimeEvents.current = [];
    listInteractions.mockResolvedValue({ interactions: [record()] });
  });

  it("restores cards and reports card_only blocking only while pending", async () => {
    const onBlockingChange = vi.fn();
    render(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onBlockingChange={onBlockingChange}
      />,
    );

    expect(await screen.findByRole("radio", { name: "甲" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "基础交互" })).toBeVisible();
    await waitFor(() =>
      expect(onBlockingChange).toHaveBeenLastCalledWith(true),
    );
  });

  it("reloads durable interactions when the completed response revision changes", async () => {
    listInteractions
      .mockResolvedValueOnce({ interactions: [] })
      .mockResolvedValueOnce({ interactions: [questionRecord()] });
    const view = render(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        responseRevision={0}
      />,
    );

    await waitFor(() => expect(listInteractions).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("textbox", { name: "服务范围？" }),
    ).not.toBeInTheDocument();

    view.rerender(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        responseRevision={1}
      />,
    );

    expect(
      await screen.findByRole("textbox", { name: "服务范围？" }),
    ).toBeVisible();
    expect(listInteractions).toHaveBeenCalledTimes(2);
  });

  it("places a card at the bottom of the reply that created it", async () => {
    render(
      <>
        <div
          data-testid="unrelated-response"
          data-super-expert-interaction-slot="interaction-other"
        />
        <article data-runtime-progress-card>
          <div
            data-testid="matching-response"
            data-super-expert-interaction-slot="interaction-1"
          />
          <p>卡片前的回复文案</p>
          <div
            data-testid="matching-response-bottom"
            data-super-expert-interaction-fallback-slot
          />
        </article>
        <InlineSuperExpertInteractionCards conversationId="conversation-1" />
      </>,
    );

    expect(
      await within(screen.getByTestId("matching-response-bottom")).findByRole(
        "region",
        { name: "基础交互" },
      ),
    ).toBeVisible();
    expect(
      within(screen.getByTestId("matching-response")).queryByRole("region", {
        name: "基础交互",
      }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("unrelated-response")).queryByRole("region", {
        name: "基础交互",
      }),
    ).not.toBeInTheDocument();
    expect(listInteractions).toHaveBeenCalledTimes(1);
  });

  it("falls back to the newest response when historical messages have no exact anchor", async () => {
    render(
      <>
        <div
          data-testid="newest-response"
          data-super-expert-interaction-fallback-slot
        />
        <div
          data-testid="older-response"
          data-super-expert-interaction-fallback-slot
        />
        <InlineSuperExpertInteractionCards conversationId="conversation-1" />
      </>,
    );

    expect(
      await within(screen.getByTestId("newest-response")).findByRole("region", {
        name: "基础交互",
      }),
    ).toBeVisible();
    expect(
      within(screen.getByTestId("older-response")).queryByRole("region", {
        name: "基础交互",
      }),
    ).not.toBeInTheDocument();
  });

  it("does not move a submitted historical card to the newest response when its exact anchor is unmounted", async () => {
    listInteractions.mockResolvedValue({
      interactions: [record(2, "SUBMITTED")],
    });
    render(
      <>
        <div
          data-testid="newest-response"
          data-super-expert-interaction-fallback-slot
        />
        <InlineSuperExpertInteractionCards conversationId="conversation-1" />
      </>,
    );

    await waitFor(() => expect(listInteractions).toHaveBeenCalledTimes(1));
    expect(
      within(screen.getByTestId("newest-response")).queryByRole("region", {
        name: "基础交互",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "基础交互" }),
    ).not.toBeInTheDocument();
  });

  it("merges a newer live event over the REST snapshot", async () => {
    const view = render(
      <SuperExpertInteractionCards conversationId="conversation-1" />,
    );
    await screen.findByRole("button", { name: "提交选择" });
    runtimeEvents.current = [
      {
        id: "event-2",
        type: "super_expert_interaction",
        scope: "session",
        payload: {
          envelope: {
            event_type: "interaction.card.submitted",
            conversation_id: "conversation-1",
            interaction: record(2, "SUBMITTED"),
          },
        },
      },
    ];
    view.rerender(
      <SuperExpertInteractionCards conversationId="conversation-1" />,
    );
    expect(await screen.findByRole("radio", { name: "甲" })).toBeDisabled();
  });

  it("does not expose a second submit action while the first request is running", async () => {
    let finishSubmission!: (value: unknown) => void;
    submitInteraction.mockReturnValue(
      new Promise((resolve) => {
        finishSubmission = resolve;
      }),
    );
    const view = render(
      <SuperExpertInteractionCards conversationId="conversation-1" />,
    );

    fireEvent.click(await screen.findByRole("radio", { name: "甲" }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));
    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(1));

    runtimeEvents.current = [
      {
        id: "event-submitted-before-response",
        type: "super_expert_interaction",
        scope: "session",
        payload: {
          envelope: {
            event_type: "interaction.card.submitted",
            conversation_id: "conversation-1",
            interaction: record(2, "SUBMITTED"),
          },
        },
      },
    ];
    view.rerender(
      <SuperExpertInteractionCards conversationId="conversation-1" />,
    );

    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
    expect(submitInteraction).toHaveBeenCalledTimes(1);

    await act(async () => {
      finishSubmission({
        interaction: record(2, "SUBMITTED"),
        user_input: "甲",
      });
    });
  });

  it("keeps card_only blocked when the submitted event beats the HTTP acknowledgement", async () => {
    const onBlockingChange = vi.fn();
    submitInteraction.mockReturnValue(new Promise(() => undefined));
    const view = render(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onBlockingChange={onBlockingChange}
      />,
    );

    fireEvent.click(await screen.findByRole("radio", { name: "甲" }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));
    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(1));
    runtimeEvents.current = [
      {
        id: "submitted-before-http-ack",
        type: "super_expert_interaction",
        scope: "session",
        payload: {
          envelope: {
            event_type: "interaction.card.submitted",
            conversation_id: "conversation-1",
            interaction: record(2, "SUBMITTED"),
          },
        },
      },
    ];
    view.rerender(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onBlockingChange={onBlockingChange}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled(),
    );
    expect(onBlockingChange).toHaveBeenLastCalledWith(true);
  });

  it("submits the trusted card output through the normal user-input callback", async () => {
    const onBlockingChange = vi.fn();
    const onSubmitAsUserInput = vi.fn();
    submitInteraction.mockResolvedValue({
      interaction: record(2, "SUBMITTED"),
      user_input: "甲",
    });
    render(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onBlockingChange={onBlockingChange}
        onSubmitAsUserInput={onSubmitAsUserInput}
      />,
    );
    fireEvent.click(await screen.findByRole("radio", { name: "甲" }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));

    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(1));
    expect(submitInteraction.mock.calls[0][0]).toBe("interaction-1");
    expect(submitInteraction.mock.calls[0][1].idempotency_key).toBeTruthy();
    await waitFor(() =>
      expect(onBlockingChange).toHaveBeenLastCalledWith(false),
    );
    expect(onSubmitAsUserInput).toHaveBeenCalledWith("甲");
    expect(onSubmitAsUserInput).toHaveBeenCalledTimes(1);
  });

  it("does not deliver an old card result after switching conversations", async () => {
    let finishSubmission!: (value: unknown) => void;
    const onSubmitAsUserInput = vi.fn();
    listInteractions.mockImplementation(async (conversationId: string) => ({
      interactions: conversationId === "conversation-1" ? [record()] : [],
    }));
    submitInteraction.mockReturnValue(
      new Promise((resolve) => {
        finishSubmission = resolve;
      }),
    );
    const view = render(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onSubmitAsUserInput={onSubmitAsUserInput}
      />,
    );

    fireEvent.click(await screen.findByRole("radio", { name: "甲" }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));
    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(1));

    view.rerender(
      <SuperExpertInteractionCards
        conversationId="conversation-2"
        onSubmitAsUserInput={onSubmitAsUserInput}
      />,
    );
    await waitFor(() =>
      expect(listInteractions).toHaveBeenCalledWith("conversation-2"),
    );
    await act(async () => {
      finishSubmission({
        interaction: record(2, "SUBMITTED"),
        user_input: "甲",
      });
    });

    expect(onSubmitAsUserInput).not.toHaveBeenCalled();
    expect(screen.queryByRole("radio", { name: "甲" })).not.toBeInTheDocument();

    view.rerender(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onSubmitAsUserInput={onSubmitAsUserInput}
      />,
    );

    await waitFor(() => expect(onSubmitAsUserInput).toHaveBeenCalledWith("甲"));
    expect(onSubmitAsUserInput).toHaveBeenCalledTimes(1);
  });

  it("can recover the ordinary user input when the submit response is lost", async () => {
    const onSubmitAsUserInput = vi.fn();
    submitInteraction
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce({
        interaction: record(2, "SUBMITTED"),
        user_input: "甲",
      });
    const view = render(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onSubmitAsUserInput={onSubmitAsUserInput}
      />,
    );

    fireEvent.click(await screen.findByRole("radio", { name: "甲" }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));
    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(1));
    runtimeEvents.current = [
      {
        id: "submitted-with-lost-response",
        type: "super_expert_interaction",
        scope: "session",
        payload: {
          envelope: {
            event_type: "interaction.card.submitted",
            conversation_id: "conversation-1",
            interaction: record(2, "SUBMITTED"),
          },
        },
      },
    ];
    view.rerender(
      <SuperExpertInteractionCards
        conversationId="conversation-1"
        onSubmitAsUserInput={onSubmitAsUserInput}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "重新提交" }));
    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(2));
    expect(submitInteraction.mock.calls[1][1].idempotency_key).toBe(
      submitInteraction.mock.calls[0][1].idempotency_key,
    );
    await waitFor(() => expect(onSubmitAsUserInput).toHaveBeenCalledWith("甲"));
    expect(onSubmitAsUserInput).toHaveBeenCalledTimes(1);
  });

  it("projects and submits question answers without choice fields", async () => {
    listInteractions.mockResolvedValue({ interactions: [questionRecord()] });
    submitInteraction.mockResolvedValue({
      interaction: questionRecord(2, "SUBMITTED"),
      user_input: "空调维修",
    });
    render(<SuperExpertInteractionCards conversationId="conversation-1" />);

    fireEvent.change(
      await screen.findByRole("textbox", { name: "服务范围？" }),
      { target: { value: "  空调维修  " } },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));

    await waitFor(() => expect(submitInteraction).toHaveBeenCalledTimes(1));
    const payload = submitInteraction.mock.calls[0][1];
    expect(payload.answers).toEqual([
      { id: "scope", value: "空调维修" },
      { question: "其他情况？", value: null },
    ]);
    expect(payload).not.toHaveProperty("selected");
    expect(payload).not.toHaveProperty("supplement");
  });
});
