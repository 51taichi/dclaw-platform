import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SceneWebviewHost from "./SceneWebviewHost";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) => {
      const labels: Record<string, string> = {
        "sceneFeedback.loadingTitle": `正在打开「${options?.name ?? ""}」`,
        "sceneFeedback.loadingSubtitle": "正在连接场景，请稍候",
        "sceneFeedback.errorTitle": "暂时无法打开这个场景",
        "sceneFeedback.errorSubtitle": "请检查网络连接后重试。",
        "taskLoading.retry": "重试",
      };
      return labels[key] ?? key;
    },
  }),
}));

describe("SceneWebviewHost", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      x: 8,
      y: 56,
      top: 56,
      right: 808,
      bottom: 656,
      left: 8,
      width: 800,
      height: 600,
      toJSON: () => ({}),
    });
  });

  it("shows friendly error feedback and retries the native webview", async () => {
    invokeMock
      .mockRejectedValueOnce(new Error("native implementation detail"))
      .mockResolvedValue(undefined);

    render(
      <SceneWebviewHost
        scene={{
          key: "support",
          title: "Agent 客服",
          url: "https://example.com",
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "正在打开「Agent 客服」",
    );
    const error = await screen.findByRole("alert");
    expect(error).toHaveAttribute("data-feedback-state", "error");
    expect(error).not.toHaveTextContent("native implementation detail");

    fireEvent.click(screen.getByRole("button", { name: /重\s*试/ }));

    await waitFor(() => expect(invokeMock).toHaveBeenCalledTimes(2));
    expect(invokeMock).toHaveBeenLastCalledWith(
      "show_scene_webview",
      expect.objectContaining({ sceneKey: "support" }),
    );
  });
});
