import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { sealedAgentsApi } from "../../../api/modules/sealedAgents";
import SealedAgentsPage from "./index";

vi.mock("../../../api/modules/sealedAgents", () => ({
  sealedAgentsApi: {
    list: vi.fn(),
    uploadRelease: vi.fn(),
    activate: vi.fn(),
    setEnabled: vi.fn(),
  },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: vi.fn(), success: vi.fn() },
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
});
