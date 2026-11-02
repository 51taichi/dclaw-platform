import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { open } from "@tauri-apps/plugin-shell";
import {
  type ChoiceInteractionProjection,
  type QuestionFormInteractionProjection,
  SuperExpertInteractionCard,
} from "./SuperExpertInteractionCard";
import { isTrustedLocalToolActionUrl } from "./localToolAction";

vi.mock("@tauri-apps/plugin-shell", () => ({ open: vi.fn() }));
const { ensureLocalHelper } = vi.hoisted(() => ({
  ensureLocalHelper: vi.fn(),
}));
vi.mock("../../../desktop/localHelper", () => ({ ensureLocalHelper }));

function single(
  overrides: Partial<ChoiceInteractionProjection> = {},
): ChoiceInteractionProjection {
  return {
    interactionId: "interaction-1",
    version: 1,
    status: "PENDING",
    inputPolicy: "card_only",
    componentType: "single_select",
    title: "请选择更合适的方向",
    description: "选项文本可能很长，必须完整展示，不能省略关键判断信息。",
    layout: "auto",
    options: [
      {
        id: "a",
        text: "方案甲：保留稳定业务 ID 与完整显示文本",
        description: "适合希望后续流程稳定引用该候选的情况。",
        recommended: true,
        defaultSelected: false,
      },
      {
        id: null,
        text: "方案乙：仅返回文本",
        description: null,
        recommended: false,
        defaultSelected: false,
      },
    ],
    supplement: {
      enabled: true,
      required: false,
      label: "补充信息（选填）",
      placeholder: "如有需要可补充",
      maxLength: 500,
    },
    minSelections: 1,
    maxSelections: 1,
    answer: null,
    ...overrides,
  };
}

function questionForm(
  overrides: Partial<QuestionFormInteractionProjection> = {},
): QuestionFormInteractionProjection {
  return {
    interactionId: "interaction-question-1",
    version: 1,
    status: "PENDING",
    inputPolicy: "card_only",
    componentType: "question_form",
    title: "请补充以下信息",
    description: "每个问题单独填写。",
    items: [
      {
        id: "scope",
        question: "服务范围？",
        description: "例如空调、冰箱或洗衣机维修。",
        placeholder: "请填写服务范围",
        required: true,
        maxLength: 20,
      },
      {
        id: null,
        question: "其他情况？",
        description: null,
        placeholder: "选填",
        required: false,
        maxLength: 50,
      },
    ],
    answer: null,
    ...overrides,
  };
}

describe("SuperExpertInteractionCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ensureLocalHelper.mockResolvedValue({ available: false, status: null });
  });

  it("only trusts DClaw bootstrap connection actions", () => {
    expect(
      isTrustedLocalToolActionUrl(
        "https://dclaw.deepmega.cn/api/bootstrap/token/connect",
      ),
    ).toBe(true);
    expect(
      isTrustedLocalToolActionUrl(
        "https://evil.test/api/bootstrap/token/connect",
      ),
    ).toBe(false);
    expect(
      isTrustedLocalToolActionUrl("dclaw-local-tool://connect?token=x"),
    ).toBe(false);
  });

  it("opens and submits a trusted desktop launch action once", async () => {
    const openExternal = vi.fn();
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: { api: { open_external_link: openExternal } },
    });
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const actionUrl = "https://dclaw.deepmega.cn/api/bootstrap/token/connect";

    render(
      <SuperExpertInteractionCard
        projection={single({
          options: [
            {
              id: "launch-local-tool",
              text: "启动本地助手",
              description: null,
              recommended: true,
              defaultSelected: true,
              actionUrl,
              autoSubmitOnDesktop: true,
            },
            {
              id: "later",
              text: "稍后处理",
              description: null,
              recommended: false,
              defaultSelected: false,
            },
          ],
        })}
        onSubmit={onSubmit}
      />,
    );

    await waitFor(() => expect(openExternal).toHaveBeenCalledWith(actionUrl));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    Reflect.deleteProperty(window, "pywebview");
  });

  it("starts the plugin-managed helper for the desktop runtime", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {},
    });
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const actionUrl =
      "https://dclaw.deepmega.cn/api/bootstrap/tauri-token/connect";
    ensureLocalHelper.mockResolvedValue({
      available: true,
      status: {
        supported: true,
        installed: true,
        running: true,
        connected: true,
        paired: true,
        deviceId: "device-1",
        runnerVersion: "1.0.0",
      },
    });

    render(
      <SuperExpertInteractionCard
        projection={single({
          interactionId: "tauri-launch",
          options: [
            {
              id: "launch-local-tool",
              text: "启动本地助手",
              description: null,
              recommended: true,
              defaultSelected: true,
              actionUrl,
              autoSubmitOnDesktop: true,
            },
            {
              id: "later",
              text: "稍后处理",
              description: null,
              recommended: false,
              defaultSelected: false,
            },
          ],
        })}
        onSubmit={onSubmit}
      />,
    );

    await waitFor(() => expect(ensureLocalHelper).toHaveBeenCalledTimes(1));
    expect(open).not.toHaveBeenCalled();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("reports a helper download failure only when a local action runs", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {},
    });
    ensureLocalHelper.mockRejectedValue(
      new Error("超级专家插件未发布可用的 Windows 本地助手。"),
    );
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(
      <SuperExpertInteractionCard
        projection={single({
          interactionId: "missing-helper",
          options: [
            {
              id: "launch-local-tool",
              text: "启动本地助手",
              description: null,
              recommended: true,
              defaultSelected: true,
              actionUrl:
                "https://dclaw.deepmega.cn/api/bootstrap/missing/connect",
              autoSubmitOnDesktop: true,
            },
          ],
        })}
        onSubmit={onSubmit}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "超级专家插件未发布可用的 Windows 本地助手。",
    );
    expect(onSubmit).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("shows only actionable choice content without repeating the prompt", () => {
    render(
      <SuperExpertInteractionCard projection={single()} onSubmit={vi.fn()} />,
    );

    expect(screen.getByText("AI 推荐")).toBeVisible();
    expect(screen.getByRole("radio", { name: /方案甲/ })).not.toBeChecked();
    expect(screen.queryByText("请选择更合适的方向")).not.toBeInTheDocument();
    expect(screen.queryByText(/选项文本可能很长/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "补充信息（选填）" }),
    ).toBeEnabled();
  });

  it("applies an explicit default and submits ID plus text reference", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <SuperExpertInteractionCard
        projection={single({
          options: single().options.map((option, index) => ({
            ...option,
            defaultSelected: index === 0,
          })),
        })}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByRole("radio", { name: /方案甲/ })).toBeChecked();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "我的补充" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        version: 1,
        selected: [{ id: "a", text: "方案甲：保留稳定业务 ID 与完整显示文本" }],
        supplement: "我的补充",
      }),
    );
  });

  it("enforces multi-select bounds and required supplement", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <SuperExpertInteractionCard
        projection={single({
          componentType: "multi_select",
          minSelections: 1,
          maxSelections: 2,
          supplement: {
            ...single().supplement,
            required: true,
            label: "请说明原因",
          },
        })}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /方案甲/ }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "请填写补充信息",
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("freezes a submitted answer and hides the submit action", () => {
    render(
      <SuperExpertInteractionCard
        projection={single({
          status: "SUBMITTED",
          version: 2,
          answer: {
            selected: [
              { id: "a", text: "方案甲：保留稳定业务 ID 与完整显示文本" },
            ],
            supplement: null,
          },
        })}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: /方案甲/ })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "提交选择" }),
    ).not.toBeInTheDocument();
  });

  it("restores editing after a failed submit and prevents duplicate clicks", async () => {
    let reject!: (reason: Error) => void;
    const onSubmit = vi.fn(
      () =>
        new Promise<void>(
          (_resolve, rejectPromise) => (reject = rejectPromise),
        ),
    );
    render(
      <SuperExpertInteractionCard projection={single()} onSubmit={onSubmit} />,
    );
    fireEvent.click(screen.getByRole("radio", { name: /方案乙/ }));
    const button = screen.getByRole("button", { name: "提交选择" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    reject(new Error("network"));
    expect(await screen.findByRole("alert")).toHaveTextContent("提交失败");
    expect(button).toBeEnabled();
  });

  it("keeps the first submission locked and visibly loading across an equivalent refresh", () => {
    const onSubmit = vi.fn(() => new Promise<void>(() => undefined));
    const view = render(
      <SuperExpertInteractionCard projection={single()} onSubmit={onSubmit} />,
    );

    fireEvent.click(screen.getByRole("radio", { name: /方案乙/ }));
    fireEvent.click(screen.getByRole("button", { name: "提交选择" }));

    const loadingButton = screen.getByRole("button", { name: "提交中…" });
    expect(loadingButton).toBeDisabled();
    expect(loadingButton).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("submit-spinner")).toBeVisible();

    view.rerender(
      <SuperExpertInteractionCard
        projection={{ ...single(), options: [...single().options] }}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "提交中…" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("keeps the submit request visibly locked after the submitted event", () => {
    render(
      <SuperExpertInteractionCard
        projection={single({
          status: "SUBMITTED",
          version: 2,
          answer: {
            selected: [{ id: null, text: "方案乙：仅返回文本" }],
            supplement: null,
          },
          submissionInFlight: true,
        })}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
  });

  it("lets short choices share a row and makes long choices span the grid", () => {
    render(
      <SuperExpertInteractionCard
        projection={single({
          layout: "list",
          options: [
            ...single().options,
            {
              id: "long",
              text: "这是一个需要完整展示的较长选择方向",
              description:
                "这里包含较长的问题背景、适用条件和后续路径，双栏显示会导致阅读拥挤，因此应当单独占一整行。",
              recommended: false,
              defaultSelected: false,
            },
          ],
        })}
        onSubmit={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("radio", { name: /方案甲/ }).closest("label"),
    ).toHaveAttribute("data-column-span", "auto");
    expect(
      screen.getByRole("radio", { name: /方案乙/ }).closest("label"),
    ).toHaveAttribute("data-column-span", "auto");
    expect(
      screen.getByRole("radio", { name: /较长选择方向/ }).closest("label"),
    ).toHaveAttribute("data-column-span", "full");
  });

  it("reserves desktop card width independently from the reply text", () => {
    render(
      <SuperExpertInteractionCard projection={single()} onSubmit={vi.fn()} />,
    );

    const card = screen.getByRole("radio", { name: /方案甲/ }).closest("form");
    expect(card).toHaveStyle({ width: "720px", maxWidth: "100%" });
  });

  it("renders question items in an adaptive grid and focuses the first missing required answer", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <SuperExpertInteractionCard
        projection={questionForm()}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getAllByTestId("question-item")).toHaveLength(2);
    expect(screen.queryByText("请补充以下信息")).not.toBeInTheDocument();
    expect(screen.queryByText("每个问题单独填写。")).not.toBeInTheDocument();
    expect(screen.getByText("必填")).toBeVisible();
    expect(screen.getByText("选填", { selector: "span" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));

    expect(await screen.findByText("请填写此项")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "服务范围？" })).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("lets short questions share a row and makes long questions span the grid", () => {
    render(
      <SuperExpertInteractionCard
        projection={questionForm({
          items: [
            ...questionForm().items,
            {
              id: "long",
              question:
                "请详细说明当前业务覆盖区域、主要客户类型、成交方式以及现阶段最希望优先解决的经营问题？",
              description:
                "这段说明也比较长，需要完整展示，避免两栏布局造成文字过度拥挤。",
              placeholder: "请填写",
              required: false,
              maxLength: 200,
            },
          ],
        })}
        onSubmit={vi.fn()}
      />,
    );

    const items = screen.getAllByTestId("question-item");
    expect(items[0]).toHaveAttribute("data-column-span", "auto");
    expect(items[1]).toHaveAttribute("data-column-span", "auto");
    expect(items[2]).toHaveAttribute("data-column-span", "full");
  });

  it("submits trimmed answers, preserves internal newlines, and includes optional null", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <SuperExpertInteractionCard
        projection={questionForm()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "服务范围？" }), {
      target: { value: "  空调\n冰箱  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        version: 1,
        answers: [
          { id: "scope", question: "服务范围？", value: "空调\n冰箱" },
          { id: null, question: "其他情况？", value: null },
        ],
      }),
    );
  });

  it("restores submitted question answers as read-only content", () => {
    render(
      <SuperExpertInteractionCard
        projection={questionForm({
          status: "SUBMITTED",
          version: 2,
          answer: {
            answers: [
              { id: "scope", question: "服务范围？", value: "空调维修" },
              { id: null, question: "其他情况？", value: null },
            ],
          },
        })}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("textbox", { name: "服务范围？" })).toHaveValue(
      "空调维修",
    );
    expect(screen.getByRole("textbox", { name: "服务范围？" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "提交回答" }),
    ).not.toBeInTheDocument();
  });
});
