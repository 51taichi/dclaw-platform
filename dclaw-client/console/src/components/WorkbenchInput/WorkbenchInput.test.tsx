import {
  createEvent,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import WorkbenchInput from "./index";
import { chatApi } from "../../api/modules/chat";

const { isDesktopRuntimeMock, readDesktopClipboardFilesMock } = vi.hoisted(
  () => ({
    isDesktopRuntimeMock: vi.fn(),
    readDesktopClipboardFilesMock: vi.fn(),
  }),
);

vi.mock("../../utils/desktopClipboard", () => ({
  isDesktopRuntime: isDesktopRuntimeMock,
  readDesktopClipboardFiles: readDesktopClipboardFilesMock,
}));

describe("WorkbenchInput file drop", () => {
  it("places mention and attachment actions in the bottom toolbar", () => {
    const { container } = renderWithProviders(
      <WorkbenchInput onSubmit={vi.fn()} />,
    );
    const footer = container.querySelector('[class*="inputFooter"]');

    expect(footer).not.toBeNull();
    expect(footer).toContainElement(screen.getByTitle("添加文件作为回答背景"));
    expect(footer).toContainElement(screen.getByTitle("添加附件"));
    expect(container.querySelector('[class*="inputToolbar"]')).toBeNull();
  });

  it("clears the file hint on cancellation and ignores text drags", () => {
    const { container } = renderWithProviders(
      <WorkbenchInput onSubmit={vi.fn()} />,
    );
    const area = container.querySelector('[class*="inputArea"]')!;
    fireEvent.dragEnter(area, { dataTransfer: { types: ["text/plain"] } });
    expect(screen.queryByText("松开即可上传附件")).not.toBeInTheDocument();
    fireEvent.dragEnter(area, { dataTransfer: { types: ["Files"] } });
    expect(screen.getByText("松开即可上传附件")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("松开即可上传附件")).not.toBeInTheDocument();
  });

  it("uploads dropped files once without sending or clearing the draft", async () => {
    const onSubmit = vi.fn();
    vi.mocked(chatApi.uploadFile).mockResolvedValue({
      url: "/attachment",
    } as never);
    const { container } = renderWithProviders(
      <WorkbenchInput onSubmit={onSubmit} />,
    );
    const area = container.querySelector('[class*="inputArea"]')!;
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "保留草稿" } });
    const files = [new File(["a"], "a.txt"), new File(["b"], "b.txt")];
    fireEvent.drop(area, { dataTransfer: { types: ["Files"], files } });
    await waitFor(() => expect(chatApi.uploadFile).toHaveBeenCalledTimes(2));
    expect(input).toHaveValue("保留草稿");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("WorkbenchInput clipboard attachments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isDesktopRuntimeMock.mockReturnValue(false);
    readDesktopClipboardFilesMock.mockResolvedValue([]);
  });

  it("uploads pasted images and files without sending or clearing the draft", async () => {
    const onSubmit = vi.fn();
    vi.mocked(chatApi.uploadFile).mockResolvedValue({
      url: "/attachment",
    } as never);
    renderWithProviders(<WorkbenchInput onSubmit={onSubmit} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "保留草稿" } });
    const image = new File(["image"], "screenshot.png", {
      type: "image/png",
    });
    const document = new File(["document"], "brief.pdf", {
      type: "application/pdf",
    });
    const pasteEvent = createEvent.paste(input, {
      clipboardData: {
        items: [
          { kind: "file", getAsFile: () => image },
          { kind: "file", getAsFile: () => document },
        ],
        files: [image, document],
      },
    });

    fireEvent(input, pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(true);
    await waitFor(() => expect(chatApi.uploadFile).toHaveBeenCalledTimes(2));
    expect(chatApi.uploadFile).toHaveBeenNthCalledWith(1, image);
    expect(chatApi.uploadFile).toHaveBeenNthCalledWith(2, document);
    expect(input).toHaveValue("保留草稿");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("leaves text-only paste to the textarea", () => {
    renderWithProviders(<WorkbenchInput onSubmit={vi.fn()} />);
    const input = screen.getByRole("textbox");
    const pasteEvent = createEvent.paste(input, {
      clipboardData: {
        items: [{ kind: "string", getAsFile: () => null }],
        files: [],
      },
    });

    fireEvent(input, pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(false);
    expect(chatApi.uploadFile).not.toHaveBeenCalled();
  });

  it("falls back to native clipboard files when the webview exposes none", async () => {
    isDesktopRuntimeMock.mockReturnValue(true);
    const nativeFile = new File(["native"], "客户名单.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    readDesktopClipboardFilesMock.mockResolvedValue([nativeFile]);
    vi.mocked(chatApi.uploadFile).mockResolvedValue({
      url: "/native-attachment",
    } as never);
    renderWithProviders(<WorkbenchInput onSubmit={vi.fn()} />);
    const input = screen.getByRole("textbox");
    const pasteEvent = createEvent.paste(input, {
      clipboardData: { items: [], files: [] },
    });

    fireEvent(input, pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(true);
    await waitFor(() =>
      expect(readDesktopClipboardFilesMock).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(chatApi.uploadFile).toHaveBeenCalledWith(nativeFile),
    );
  });

  it("preserves a text-only paste in the desktop runtime", async () => {
    isDesktopRuntimeMock.mockReturnValue(true);
    renderWithProviders(<WorkbenchInput onSubmit={vi.fn()} />);
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "前后" } });
    input.setSelectionRange(1, 1);
    const pasteEvent = createEvent.paste(input, {
      clipboardData: {
        items: [{ kind: "string", getAsFile: () => null }],
        files: [],
        getData: () => "普通文字",
      },
    });

    fireEvent(input, pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(true);
    await waitFor(() => expect(input).toHaveValue("前普通文字后"));
    expect(chatApi.uploadFile).not.toHaveBeenCalled();
  });
});

const {
  mockSpeechStart,
  mockSpeechStop,
  mockSpeechDestroy,
  mockTranscribeAudio,
} = vi.hoisted(() => ({
  mockSpeechStart: vi.fn(),
  mockSpeechStop: vi.fn(),
  mockSpeechDestroy: vi.fn(),
  mockTranscribeAudio: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("../../features/realtimeSpeech/RealtimeSpeechController", () => ({
  RealtimeSpeechController: class {
    private options: {
      onTranscript: (text: string, final: boolean) => void;
      onStateChange: (state: string) => void;
    };

    constructor(options: {
      onTranscript: (text: string, final: boolean) => void;
      onStateChange: (state: string) => void;
    }) {
      this.options = options;
    }

    start = () => {
      mockSpeechStart();
      this.options.onStateChange("recording");
    };

    stop = () => {
      mockSpeechStop();
      this.options.onTranscript("测试语音", true);
      this.options.onStateChange("idle");
    };

    destroy = mockSpeechDestroy;
  },
}));

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: () => ({
    clawSelectedAgent: "default",
    selectedAgent: "default",
    selectedExpertTeam: null,
    setAgents: vi.fn(),
  }),
}));

vi.mock("../../pages/Chat/components/ChatToolbar", () => ({
  default: () => <div data-testid="chat-toolbar" />,
}));

vi.mock("../../pages/Chat/utils/skillTargetInstall", () => ({
  ensureSkillInstalledForAgent: vi.fn(),
  resolveSkillInstallAgentId: vi.fn(() => "default"),
}));

vi.mock("../../api/modules/agents", () => ({
  agentsApi: { listAgents: vi.fn().mockResolvedValue({ agents: [] }) },
}));

vi.mock("../../api/modules/chat", () => ({
  chatApi: { uploadFile: vi.fn() },
}));

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: { listAllFiles: vi.fn(), loadRawFile: vi.fn() },
}));

vi.mock("../../api/modules/agent", () => ({
  agentApi: { transcribeAudio: mockTranscribeAudio },
  TranscriptionError: class extends Error {},
}));

describe("WorkbenchInput realtime speech", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("uses realtime dictation for consecutive task-page recordings", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchInput onSubmit={vi.fn()} />, {
      initialEntries: ["/task/test-chat"],
    });

    const microphone = await screen.findByRole("button", {
      name: "开始语音输入",
    });
    await user.click(microphone);
    expect(mockSpeechStart).toHaveBeenCalledTimes(1);

    fireEvent.click(microphone);
    expect(mockSpeechStop).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveValue("测试语音"),
    );

    await user.click(microphone);
    expect(mockSpeechStart).toHaveBeenCalledTimes(2);
    expect(mockTranscribeAudio).not.toHaveBeenCalled();
  });

  it("disables every message-producing input while a card_only interaction is active", async () => {
    renderWithProviders(<WorkbenchInput onSubmit={vi.fn()} disabled />, {
      initialEntries: ["/task/test-chat"],
    });

    expect(
      screen.getByText("请先完成上方交互卡片，提交后即可继续输入"),
    ).toBeVisible();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByTitle("添加文件作为回答背景")).toBeDisabled();
    expect(screen.getByTitle("添加附件")).toBeDisabled();
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeDisabled();
    expect(screen.getByTitle("发送")).toBeDisabled();
  });
});
