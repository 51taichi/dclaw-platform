import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import WorkbenchInput from "./index";

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
});
