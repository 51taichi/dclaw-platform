import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import LocalAccessSelector from "./LocalAccessSelector";

const { getLocalAccessMode, setLocalAccessMode, showError } = vi.hoisted(
  () => ({
    getLocalAccessMode: vi.fn(),
    setLocalAccessMode: vi.fn(),
    showError: vi.fn(),
  }),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: showError } }),
}));

vi.mock("../sessionApi", () => ({
  default: { getLocalAccessMode, setLocalAccessMode },
  DRAFT_SESSION_ID: "draft-session",
  DEFAULT_LOCAL_ACCESS_MODE: "ask_for_approval",
}));

describe("LocalAccessSelector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getLocalAccessMode.mockResolvedValue("ask_for_approval");
    setLocalAccessMode.mockImplementation(
      async (_chatId: string, mode: string) => mode,
    );
  });

  it("defaults to asking before actions and shows both permission choices", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LocalAccessSelector chatId="chat-1" />);

    const trigger = await screen.findByRole("button", {
      name: /操作前询问/,
    });
    await user.click(trigger);

    expect(
      screen.getByRole("menuitemradio", { name: /操作前询问/ }),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByRole("menuitemradio", { name: /允许完全访问/ }),
    ).toHaveAttribute("aria-checked", "false");
  });

  it("persists full access for the current chat", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <LocalAccessSelector chatId="chat-1" agentId="agent-1" />,
    );

    await user.click(await screen.findByRole("button", { name: /操作前询问/ }));
    await user.click(
      screen.getByRole("menuitemradio", { name: /允许完全访问/ }),
    );

    await waitFor(() =>
      expect(setLocalAccessMode).toHaveBeenCalledWith(
        "chat-1",
        "full_access",
        "agent-1",
      ),
    );
    expect(
      screen.getByRole("button", { name: /允许完全访问/ }),
    ).toBeInTheDocument();
  });

  it("keeps the current choice and reports a save failure", async () => {
    const user = userEvent.setup();
    setLocalAccessMode.mockRejectedValueOnce(new Error("save failed"));
    renderWithProviders(<LocalAccessSelector chatId="chat-1" />);

    await user.click(await screen.findByRole("button", { name: /操作前询问/ }));
    await user.click(
      screen.getByRole("menuitemradio", { name: /允许完全访问/ }),
    );

    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith("权限设置保存失败"),
    );
    expect(
      screen.getByRole("button", { name: /操作前询问/ }),
    ).toBeInTheDocument();
  });
});
