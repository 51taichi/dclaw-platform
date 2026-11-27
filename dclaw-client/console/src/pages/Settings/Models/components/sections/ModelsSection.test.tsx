import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModelsSection } from "./ModelsSection";
import type { ProviderInfo } from "../../../../../api/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      error: vi.fn(),
      success: vi.fn(),
    },
  }),
}));

vi.mock("../../../../../api", () => ({
  default: {
    setActiveLlm: vi.fn(),
  },
}));

vi.mock("@/utils/freeModelSwitchWarning", () => ({
  confirmFreeModelSwitch: vi.fn().mockResolvedValue(true),
}));

vi.mock("@agentscope-ai/design", () => ({
  Button: ({ children, ...props }: React.PropsWithChildren) => (
    <button {...props}>{children}</button>
  ),
  Card: ({ children, title }: React.PropsWithChildren<{ title?: string }>) => (
    <section aria-label={title}>{children}</section>
  ),
  Select: ({
    options = [],
    placeholder,
  }: {
    options?: Array<{ value: string; label: string; disabled?: boolean }>;
    placeholder?: string;
  }) => (
    <select aria-label={placeholder}>
      {options.map((option) => (
        <option
          key={option.value}
          value={option.value}
          disabled={option.disabled}
        >
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

const buildProvider = (overrides: Partial<ProviderInfo>): ProviderInfo => ({
  id: "provider",
  name: "Provider",
  api_key_prefix: "",
  chat_model: "OpenAIChatModel",
  models: [
    {
      id: "model",
      name: "Model",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
    },
  ],
  extra_models: [],
  is_custom: false,
  is_local: false,
  support_model_discovery: false,
  support_connection_check: true,
  freeze_url: true,
  require_api_key: true,
  api_key: "sk-******",
  base_url: "https://example.com/v1",
  generate_kwargs: {},
  ...overrides,
});

describe("ModelsSection", () => {
  it("filters disabled providers from the default model provider list", () => {
    render(
      <ModelsSection
        providers={[
          buildProvider({ id: "enabled", name: "Enabled Provider" }),
          buildProvider({
            id: "disabled",
            name: "Disabled Provider",
            disabled: true,
          }),
        ]}
        activeModels={null}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("Enabled Provider")).toBeInTheDocument();
    expect(screen.queryByText("Disabled Provider")).not.toBeInTheDocument();
  });

  it("keeps embedding models out of the default LLM selector", () => {
    render(
      <ModelsSection
        providers={[
          buildProvider({
            models: [
              {
                id: "chat-model",
                name: "Chat Model",
                model_type: "llm",
                supports_multimodal: false,
                supports_image: false,
                supports_video: false,
                generate_kwargs: {},
              },
              {
                id: "embedding-model",
                name: "Embedding Model",
                model_type: "embedding",
                supports_multimodal: false,
                supports_image: false,
                supports_video: false,
                generate_kwargs: {},
              },
            ],
          }),
        ]}
        activeModels={{
          active_llm: { provider_id: "provider", model: "chat-model" },
        }}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("Chat Model (chat-model)")).toBeInTheDocument();
    expect(
      screen.queryByText("Embedding Model (embedding-model)"),
    ).not.toBeInTheDocument();
  });

  it("shows unpriced LLM models but prevents selecting them", () => {
    render(
      <ModelsSection
        providers={[
          buildProvider({
            models: [
              {
                id: "unpriced-model",
                name: "Unpriced Model",
                billing_eligible: false,
                supports_multimodal: false,
                supports_image: false,
                supports_video: false,
                generate_kwargs: {},
              },
            ],
          }),
        ]}
        activeModels={{
          active_llm: { provider_id: "provider", model: "unpriced-model" },
        }}
        onSaved={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("option", { name: /models\.unpriced/ }),
    ).toBeDisabled();
  });
});
