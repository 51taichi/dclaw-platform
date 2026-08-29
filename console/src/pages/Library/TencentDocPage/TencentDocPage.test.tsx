import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TencentDocPage from "./index";

const { mockRequest } = vi.hoisted(() => ({
  mockRequest: vi.fn(),
}));

vi.mock("../../../api", () => ({ request: mockRequest }));

vi.mock("@/components/AgentExperienceLibrary", () => ({
  AgentExperienceLibrary: () => (
    <div data-testid="shared-agent-experience-library">共享经验库组件</div>
  ),
}));

describe("TencentDocPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequest.mockImplementation((path: string) => {
      if (path.startsWith("/workspace/knowledge/docs"))
        return Promise.resolve([]);
      if (path.startsWith("/workspace/wiki/list")) {
        return Promise.resolve({ concepts: [] });
      }
      if (path === "/workspace/mindspace/connectors") {
        return Promise.resolve({ connectors: [] });
      }
      if (path === "/user/mindspace-cloud/accounts") {
        return Promise.resolve({ providers: [], accounts: [] });
      }
      if (path === "/workspace/knowledge/capabilities") {
        return Promise.resolve({ semantic_search_enabled: false });
      }
      return Promise.resolve({});
    });
  });

  it("shows the shared library under 我的Agent经验库 without legacy controls", async () => {
    const user = userEvent.setup();
    render(<TencentDocPage />);

    await waitFor(() => {
      expect(mockRequest).toHaveBeenCalled();
    });
    mockRequest.mockClear();

    await user.click(screen.getByText("我的Agent经验库"));

    expect(
      await screen.findByTestId("shared-agent-experience-library"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "上传本地文档" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "关联云文档" }),
    ).not.toBeInTheDocument();
    expect(mockRequest).not.toHaveBeenCalled();
  });
});
