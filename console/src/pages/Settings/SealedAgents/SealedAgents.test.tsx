import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { sealedAgentsApi } from "../../../api/modules/sealedAgents";
import { ApiRequestError } from "../../../api/request";
import SealedAgentsPage from "./index";

vi.mock("../../../api/modules/sealedAgents", () => ({
  sealedAgentsApi: {
    list: vi.fn(),
    uploadRelease: vi.fn(),
    activate: vi.fn(),
    setEnabled: vi.fn(),
  },
}));

const { messageError, messageSuccess } = vi.hoisted(() => ({
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: messageError, success: messageSuccess },
  }),
}));

describe("SealedAgentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(sealedAgentsApi.list).mockResolvedValue([]);
  });

  it("uses the same name as the super expert navigation item", async () => {
    render(<SealedAgentsPage />);

    expect(screen.getByText("设置")).toBeInTheDocument();
    expect(screen.getByText("超级专家")).toBeInTheDocument();
    expect(
      await screen.findByText("暂无密封 Agent，可上传签名发布包开始使用"),
    ).toBeInTheDocument();
  });

  it("sorts historical versions and activates the selected release", async () => {
    const user = userEvent.setup();
    vi.mocked(sealedAgentsApi.list).mockResolvedValue([
      {
        agent_id: "luyu_traffic_operator",
        name: "陆羽",
        description: "",
        enabled: true,
        availability: "available",
        active_release_id: "release-202",
        version: "2.0.2",
        signer_id: "release-signer",
        releases: [
          release("release-2010", "2.0.10"),
          release("release-200", "2.0.0"),
          release("release-202", "2.0.2"),
          release("release-210", "2.1.0"),
        ],
        capabilities: {
          invoke: true,
          inspect: false,
          edit: false,
          clone: false,
          export: false,
          download: false,
          trace: false,
        },
      },
    ]);
    vi.mocked(sealedAgentsApi.activate).mockResolvedValue({} as never);

    render(<SealedAgentsPage />);

    const selector = await screen.findByRole("combobox", {
      name: "选择陆羽的历史版本",
    });
    expect(
      screen.queryByRole("button", { name: "激活 2.0.0" }),
    ).not.toBeInTheDocument();
    await user.click(selector);
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "2.1.0",
      "2.0.10",
      "2.0.0",
    ]);

    await user.click(screen.getByRole("option", { name: "2.0.10" }));
    await user.click(screen.getByRole("button", { name: "激活" }));
    expect(sealedAgentsApi.activate).toHaveBeenCalledWith(
      "luyu_traffic_operator",
      "release-2010",
    );
  });

  it("shows the backend error when release activation fails", async () => {
    const user = userEvent.setup();
    vi.mocked(sealedAgentsApi.list).mockResolvedValue([
      {
        agent_id: "luyu_traffic_operator",
        name: "陆羽",
        description: "",
        enabled: true,
        availability: "available",
        active_release_id: "release-204",
        version: "2.0.4",
        signer_id: "release-signer",
        releases: [
          release("release-204", "2.0.4"),
          release("release-210", "2.1.0"),
        ],
        capabilities: {
          invoke: true,
          inspect: false,
          edit: false,
          clone: false,
          export: false,
          download: false,
          trace: false,
        },
      },
    ]);
    vi.mocked(sealedAgentsApi.activate).mockRejectedValue(
      new ApiRequestError(
        'sealed agent runtime validation failed - {"detail":"sealed agent runtime validation failed"}',
        400,
      ),
    );

    render(<SealedAgentsPage />);

    const selector = await screen.findByRole("combobox", {
      name: "选择陆羽的历史版本",
    });
    await user.click(selector);
    await user.click(await screen.findByRole("option", { name: "2.1.0" }));
    await user.click(screen.getByRole("button", { name: "激活" }));

    await waitFor(() =>
      expect(messageError).toHaveBeenCalledWith(
        "sealed agent runtime validation failed",
      ),
    );
    expect(messageSuccess).not.toHaveBeenCalled();
  });
});

function release(releaseId: string, version: string) {
  return {
    release_id: releaseId,
    version,
    content_digest: "digest",
    signer_id: "release-signer",
    state: "installed",
    installed_at: "2026-09-01T00:00:00Z",
  };
}
