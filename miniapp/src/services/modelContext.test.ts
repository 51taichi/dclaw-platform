import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  request: vi.fn(),
  requestRoot: vi.fn(),
}));

import { requestRoot } from "./api";
import {
  AUTO_MODEL_OPTION,
  getActiveModelId,
  getModelSelectionUnavailableMessage,
  listModelOptions,
  setActiveModel,
} from "./modelContext";

const mockRequestRoot = vi.mocked(requestRoot);

describe("mobile model context helpers", () => {
  beforeEach(() => {
    mockRequestRoot.mockReset();
  });

  it("lists Auto first and keeps only chat-selectable enabled provider models", async () => {
    mockRequestRoot.mockResolvedValueOnce([
      {
        id: "openai",
        name: "OpenAI",
        api_key: "sk-test",
        models: [
          { id: "gpt-4o", name: "GPT-4o", model_type: "llm" },
          {
            id: "text-embedding-v4",
            name: "Text Embedding V4",
            model_type: "embedding",
          },
          {
            id: "image-gen",
            name: "Image Gen",
            model_type: "image",
            aigc_capabilities: ["text_to_image"],
          },
          {
            id: "video-gen",
            name: "Video Gen",
            model_type: "video",
          },
        ],
        extra_models: [{ id: "gpt-4.1-mini", name: "GPT-4.1 mini" }],
      },
      {
        id: "disabled",
        name: "Disabled",
        api_key: "sk-disabled",
        disabled: true,
        models: [{ id: "hidden", name: "Hidden" }],
      },
      {
        id: "unconfigured",
        name: "Unconfigured",
        models: [{ id: "hidden-2", name: "Hidden 2" }],
      },
    ]);

    await expect(listModelOptions()).resolves.toEqual([
      AUTO_MODEL_OPTION,
      {
        id: "openai/gpt-4o",
        name: "GPT-4o",
        provider: "OpenAI",
      },
      {
        id: "openai/gpt-4.1-mini",
        name: "GPT-4.1 mini",
        provider: "OpenAI",
      },
    ]);
  });

  it("sets Auto routing at agent scope before the task chat exists", async () => {
    mockRequestRoot.mockResolvedValueOnce({ active_llm: undefined });

    await setActiveModel({
      modelId: "",
      agentId: "default",
    });

    expect(mockRequestRoot).toHaveBeenCalledWith(
      "/models/active",
      expect.objectContaining({
        method: "PUT",
        data: {
          provider_id: "auto",
          model: "routing",
          scope: "agent",
          agent_id: "default",
        },
      }),
    );
  });

  it("sets Auto routing at chat scope once a task chat exists", async () => {
    mockRequestRoot.mockResolvedValueOnce({ active_llm: undefined });

    await setActiveModel({
      modelId: "",
      agentId: "default",
      chatId: "chat-1",
    });

    expect(mockRequestRoot).toHaveBeenCalledWith(
      "/models/active",
      expect.objectContaining({
        method: "PUT",
        data: {
          provider_id: "auto",
          model: "routing",
          scope: "chat",
          agent_id: "default",
          chat_id: "chat-1",
        },
      }),
    );
  });

  it("sets a concrete model at chat scope", async () => {
    mockRequestRoot.mockResolvedValueOnce({
      active_llm: {
        provider_id: "openai",
        model: "gpt-4o",
      },
    });

    await setActiveModel({
      modelId: "openai/gpt-4o",
      agentId: "default",
      chatId: "chat-1",
    });

    expect(mockRequestRoot).toHaveBeenCalledWith(
      "/models/active",
      expect.objectContaining({
        method: "PUT",
        data: {
          provider_id: "openai",
          model: "gpt-4o",
          scope: "chat",
          agent_id: "default",
          chat_id: "chat-1",
        },
      }),
    );
  });

  it("reads the chat active model and maps Auto routing back to Auto", async () => {
    mockRequestRoot.mockResolvedValueOnce({
      active_llm: {
        provider_id: "auto",
        model: "routing",
      },
    });

    await expect(
      getActiveModelId({ agentId: "default", chatId: "chat-1" }),
    ).resolves.toBe("");
    expect(mockRequestRoot).toHaveBeenCalledWith(
      "/models/active?scope=chat&agent_id=default&chat_id=chat-1",
    );
  });

  it("explains when there are no concrete models beyond Auto", () => {
    expect(getModelSelectionUnavailableMessage([AUTO_MODEL_OPTION])).toBe(
      "当前仅支持 Auto",
    );
    expect(
      getModelSelectionUnavailableMessage([
        AUTO_MODEL_OPTION,
        { id: "openai/gpt-4o", name: "GPT-4o" },
      ]),
    ).toBe("");
  });
});
