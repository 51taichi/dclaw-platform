import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import WorkbenchPage from "./index";

let currentPathname = "";
let currentLocationState: unknown = null;

const { mockCreateChat, mockUploadFile, mockUseAgentStore } = vi.hoisted(() => {
  const store = vi.fn(() => ({
    selectedAgent: "default",
    setSelectedAgent: vi.fn(),
    selectedSkill: null,
    setSelectedSkill: vi.fn(),
    activeMode: "craft",
    setActiveMode: vi.fn(),
    selectedExpertTeam: null,
    setSelectedExpertTeam: vi.fn(),
  })) as any;
  store.getState = vi.fn(() => ({ selectedExpertTeam: null }));

  return {
    mockCreateChat: vi.fn(),
    mockUploadFile: vi.fn(),
    mockUseAgentStore: store,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("../../api", () => ({
  default: {
    createChat: mockCreateChat,
  },
}));

vi.mock("../../api/modules/expertTeams", () => ({
  expertTeamsApi: {
    getExpertTeam: vi.fn(),
  },
}));

vi.mock("../../api/modules/chat", () => ({
  chatApi: {
    uploadFile: mockUploadFile,
  },
}));

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: mockUseAgentStore,
}));

vi.mock("../Chat/components/ChatToolbar", () => ({
  default: () => <div data-testid="chat-toolbar" />,
}));

vi.mock("../Chat/utils/skillTargetInstall", () => ({
  ensureSkillInstalledForAgent: vi.fn(),
  resolveSkillInstallAgentId: vi.fn(() => "default"),
}));

function LocationProbe() {
  const location = useLocation();
  currentPathname = location.pathname;
  currentLocationState = location.state;
  return null;
}

describe("WorkbenchPage", () => {
  beforeEach(() => {
    currentPathname = "";
    currentLocationState = null;
    (window as any).currentUserId = "1";
    (window as any).currentChannel = "claw";
    mockCreateChat.mockResolvedValue({
      id: "new-task-id",
      name: "hello",
      session_id: "new-task-id",
      user_id: "1",
      channel: "console",
      created_at: null,
      updated_at: null,
      meta: {},
    });
    mockUploadFile.mockResolvedValue({
      url: "uploads/report.pdf",
      file_name: "report.pdf",
    });
  });

  afterEach(() => {
    delete (window as any).currentUserId;
    delete (window as any).currentChannel;
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it("creates workbench tasks on the console channel even after visiting Claw", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(
      <>
        <LocationProbe />
        <WorkbenchPage />
      </>,
      { initialEntries: ["/workbench"] },
    );

    await user.type(
      screen.getByPlaceholderText("workbench.inputPlaceholder"),
      "hello",
    );
    const sendButton = container.querySelector(
      'button[class*="sendBtn"]',
    ) as HTMLButtonElement | null;

    expect(sendButton).not.toBeNull();
    await user.click(sendButton!);

    await waitFor(() =>
      expect(mockCreateChat).toHaveBeenCalledWith(
        expect.objectContaining({
          channel: "console",
          session_id: "",
          user_id: "1",
        }),
      ),
    );
    await waitFor(() => expect(currentPathname).toBe("/task/new-task-id"));
    expect(
      JSON.parse(
        sessionStorage.getItem("qwenpaw_pending_task_intent_new-task-id") || "",
      ),
    ).toEqual(
      expect.objectContaining({
        prompt: "hello",
        agentId: "default",
      }),
    );
  });

  it("uploads selected files and includes them in the first task prompt", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(
      <>
        <LocationProbe />
        <WorkbenchPage />
      </>,
      { initialEntries: ["/workbench"] },
    );

    await user.type(
      screen.getByPlaceholderText("workbench.inputPlaceholder"),
      "analyze this",
    );

    const fileInput = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement | null;
    expect(fileInput).not.toBeNull();

    const file = new File(["hello"], "report.pdf", {
      type: "application/pdf",
    });
    await user.upload(fileInput!, file);

    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledWith(file));
    expect(await screen.findByText("report.pdf")).toBeInTheDocument();

    const sendButton = container.querySelector(
      'button[class*="sendBtn"]',
    ) as HTMLButtonElement | null;
    expect(sendButton).not.toBeNull();
    await user.click(sendButton!);

    await waitFor(() => expect(currentPathname).toBe("/task/new-task-id"));
    expect((currentLocationState as any)?.intent?.prompt).toContain(
      "[report.pdf](uploads/report.pdf)",
    );
  });

  it("uploads dropped files from the new-task composer", async () => {
    const { container } = renderWithProviders(
      <>
        <LocationProbe />
        <WorkbenchPage />
      </>,
      { initialEntries: ["/workbench"] },
    );

    const inputArea = container.querySelector(
      '[class*="inputArea"]',
    ) as HTMLElement | null;
    expect(inputArea).not.toBeNull();

    const file = new File(["hello"], "dragged.txt", {
      type: "text/plain",
    });
    fireEvent.drop(inputArea!, {
      dataTransfer: {
        types: ["Files"],
        files: [file],
        dropEffect: "copy",
      },
    });

    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledWith(file));
    expect(await screen.findByText("dragged.txt")).toBeInTheDocument();
  });
});
