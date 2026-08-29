import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentExperienceLibrary } from "./index";

const { mockApi, mockMessage } = vi.hoisted(() => ({
  mockApi: {
    listPublications: vi.fn(),
    listDocuments: vi.fn(),
    uploadDocument: vi.fn(),
    syncDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
  mockMessage: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/api/modules/agentExperienceLibrary", () => ({
  agentExperienceLibraryApi: mockApi,
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

const publication = {
  id: "pub-1",
  public_id: "support_agent",
  name: "客服入口",
  target_type: "agent" as const,
  target_id: "agent-1",
  target_name: "客服专家",
  status: "enabled" as const,
  knowledge_base_id: "openapi-pub-1",
};

describe("AgentExperienceLibrary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listPublications.mockResolvedValue([publication]);
    mockApi.listDocuments.mockResolvedValue([
      { id: "doc-1", name: "产品手册.pdf", status: "ready" },
    ]);
  });

  it("shows readable agent publication labels and loads its documents", async () => {
    render(<AgentExperienceLibrary />);

    expect(
      (await screen.findAllByText("客服专家 · 客服入口 · support_agent"))
        .length,
    ).toBeGreaterThan(0);
    expect(await screen.findByText("产品手册.pdf")).toBeInTheDocument();
  });

  it("shows guidance instead of upload when no publication is accessible", async () => {
    mockApi.listPublications.mockResolvedValue([]);

    render(<AgentExperienceLibrary />);

    expect(
      await screen.findByText("暂无可维护的 Agent 经验库"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "上传文档" }),
    ).not.toBeInTheDocument();
  });

  it("allows maintaining a disabled publication and labels its state", async () => {
    mockApi.listPublications.mockResolvedValue([
      { ...publication, status: "disabled" },
    ]);

    render(<AgentExperienceLibrary />);

    expect(await screen.findByText("接口已禁用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传文档" })).toBeEnabled();
  });

  it("uploads a selected file and refreshes the current documents", async () => {
    const user = userEvent.setup();
    mockApi.uploadDocument.mockResolvedValue({
      id: "doc-2",
      name: "FAQ.txt",
      status: "ready",
    });

    render(<AgentExperienceLibrary />);
    await screen.findByText("产品手册.pdf");
    const input = screen.getByLabelText("上传经验文档");
    await user.upload(input, new File(["faq"], "FAQ.txt"));

    await waitFor(() => {
      expect(mockApi.uploadDocument).toHaveBeenCalledWith(
        "pub-1",
        expect.objectContaining({ name: "FAQ.txt" }),
      );
      expect(mockApi.listDocuments).toHaveBeenCalledTimes(2);
    });
  });

  it("rechecks accessible publications after a 404 operation", async () => {
    const user = userEvent.setup();
    const error = Object.assign(new Error("not found"), { status: 404 });
    mockApi.syncDocument.mockRejectedValue(error);
    mockApi.listPublications
      .mockResolvedValueOnce([publication])
      .mockResolvedValueOnce([]);

    render(<AgentExperienceLibrary />);
    await user.click(await screen.findByRole("button", { name: "重建索引" }));

    expect(
      await screen.findByText("暂无可维护的 Agent 经验库"),
    ).toBeInTheDocument();
    expect(mockApi.listPublications).toHaveBeenCalledTimes(2);
  });
});
