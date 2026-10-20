import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import {
  createEvent,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import WorkbenchPage from "./index";

let currentPathname = "";
let currentLocationState: unknown = null;

const {
  mockCreateChat,
  mockUploadFile,
  mockUseAgentStore,
  mockSpeechStart,
  mockSpeechStop,
  mockSpeechDestroy,
  mockIsDesktopRuntime,
  mockReadDesktopClipboardFiles,
} = vi.hoisted(() => {
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
    mockSpeechStart: vi.fn(),
    mockSpeechStop: vi.fn(),
    mockSpeechDestroy: vi.fn(),
    mockIsDesktopRuntime: vi.fn(),
    mockReadDesktopClipboardFiles: vi.fn(),
  };
});

vi.mock("../../utils/desktopClipboard", () => ({
  isDesktopRuntime: mockIsDesktopRuntime,
  readDesktopClipboardFiles: mockReadDesktopClipboardFiles,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("../../features/realtimeSpeech/RealtimeSpeechController", () => ({
  RealtimeSpeechController: class {
    private options: { onStateChange: (state: string) => void };

    constructor(options: { onStateChange: (state: string) => void }) {
      this.options = options;
    }

    start = () => {
      mockSpeechStart();
      this.options.onStateChange("recording");
    };

    stop = () => {
      mockSpeechStop();
      this.options.onStateChange("idle");
    };

    destroy = mockSpeechDestroy;
  },
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
    mockIsDesktopRuntime.mockReturnValue(false);
    mockReadDesktopClipboardFiles.mockResolvedValue([]);
  });

  afterEach(() => {
    delete (window as any).currentUserId;
    delete (window as any).currentChannel;
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it("places mention and attachment actions in the bottom toolbar", () => {
    const { container } = renderWithProviders(<WorkbenchPage />, {
      initialEntries: ["/workbench"],
    });
    const footer = container.querySelector('[class*="inputFooter"]');

    expect(footer).not.toBeNull();
    expect(footer).toContainElement(screen.getByTitle("@"));
    expect(footer).toContainElement(screen.getByTitle("添加附件"));
    expect(container.querySelector('[class*="inputToolbar"]')).toBeNull();
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

    const drag = { dataTransfer: { types: ["Files"] } };
    fireEvent.dragEnter(inputArea!, drag);
    expect(screen.getByText("松开即可上传附件")).toBeInTheDocument();
    fireEvent.dragEnter(screen.getByRole("textbox"), drag);
    fireEvent.dragLeave(screen.getByRole("textbox"), drag);
    expect(screen.getByText("松开即可上传附件")).toBeInTheDocument();
    fireEvent.dragLeave(inputArea!, drag);
    expect(screen.queryByText("松开即可上传附件")).not.toBeInTheDocument();
    fireEvent.dragEnter(inputArea!, drag);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("松开即可上传附件")).not.toBeInTheDocument();

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
    expect(mockCreateChat).not.toHaveBeenCalled();
  });

  it("uploads files pasted into the new-task composer in a browser", async () => {
    renderWithProviders(<WorkbenchPage />, {
      initialEntries: ["/workbench"],
    });
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "保留草稿" } });
    const document = new File(["document"], "客户资料.pdf", {
      type: "application/pdf",
    });
    const pasteEvent = createEvent.paste(input, {
      clipboardData: {
        items: [{ kind: "file", getAsFile: () => document }],
        files: [document],
      },
    });

    fireEvent(input, pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(true);
    await waitFor(() => expect(mockUploadFile).toHaveBeenCalledWith(document));
    expect(await screen.findByText("客户资料.pdf")).toBeInTheDocument();
    expect(input).toHaveValue("保留草稿");
  });

  it("uses native clipboard files in the desktop new-task composer", async () => {
    mockIsDesktopRuntime.mockReturnValue(true);
    const spreadsheet = new File(["sheet"], "客户名单.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    mockReadDesktopClipboardFiles.mockResolvedValue([spreadsheet]);
    renderWithProviders(<WorkbenchPage />, {
      initialEntries: ["/workbench"],
    });
    const input = screen.getByRole("textbox");
    const pasteEvent = createEvent.paste(input, {
      clipboardData: { items: [], files: [], getData: () => "" },
    });

    fireEvent(input, pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(true);
    await waitFor(() =>
      expect(mockReadDesktopClipboardFiles).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(mockUploadFile).toHaveBeenCalledWith(spreadsheet),
    );
  });

  it("keeps text-only paste behavior in browser and desktop composers", async () => {
    const { rerender } = renderWithProviders(<WorkbenchPage />, {
      initialEntries: ["/workbench"],
    });
    let input = screen.getByRole("textbox") as HTMLTextAreaElement;
    const browserPaste = createEvent.paste(input, {
      clipboardData: {
        items: [{ kind: "string", getAsFile: () => null }],
        files: [],
      },
    });
    fireEvent(input, browserPaste);
    expect(browserPaste.defaultPrevented).toBe(false);

    mockIsDesktopRuntime.mockReturnValue(true);
    rerender(<WorkbenchPage />);
    input = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "前后" } });
    input.setSelectionRange(1, 1);
    const desktopPaste = createEvent.paste(input, {
      clipboardData: {
        items: [{ kind: "string", getAsFile: () => null }],
        files: [],
        getData: () => "文字",
      },
    });
    fireEvent(input, desktopPaste);

    expect(desktopPaste.defaultPrevented).toBe(true);
    await waitFor(() => expect(input).toHaveValue("前文字后"));
    expect(mockUploadFile).not.toHaveBeenCalled();
  });

  it("starts and stops dictation without sending the task", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<WorkbenchPage />, {
      initialEntries: ["/workbench"],
    });
    const microphone = container.querySelector(
      'button[aria-label="开始语音输入"]',
    ) as HTMLButtonElement | null;

    expect(microphone).not.toBeNull();
    await user.click(microphone!);
    expect(mockSpeechStart).toHaveBeenCalledTimes(1);
    expect(mockCreateChat).not.toHaveBeenCalled();

    fireEvent.click(microphone!);
    expect(mockSpeechStop).toHaveBeenCalledTimes(1);
    expect(mockCreateChat).not.toHaveBeenCalled();
  });
});
