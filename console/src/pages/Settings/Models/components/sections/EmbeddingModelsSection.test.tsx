import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProviderInfo } from "../../../../../api/types";
import { EmbeddingModelsSection } from "./EmbeddingModelsSection";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: vi.fn(), success: vi.fn() },
  }),
}));

vi.mock("../../../../../api", () => ({
  default: {
    setActiveEmbedding: vi.fn(),
    clearActiveEmbedding: vi.fn(),
  },
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
    options?: Array<{ value: string; label: string }>;
    placeholder?: string;
  }) => (
    <select aria-label={placeholder}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

const provider: ProviderInfo = {
  id: "custom-embedding",
  name: "Custom Embedding",
  api_key_prefix: "",
  chat_model: "OpenAIChatModel",
  models: [],
  extra_models: [
    {
      id: "embedding-model",
      name: "Embedding Model",
      model_type: "embedding",
      embedding_protocol: "openai_compatible",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
    },
  ],
  is_custom: true,
  is_local: false,
  support_model_discovery: false,
  support_connection_check: true,
  freeze_url: false,
  require_api_key: true,
  api_key: "",
  base_url: "http://127.0.0.1:8080/v1",
  generate_kwargs: {},
};

describe("EmbeddingModelsSection", () => {
  it("supports an active custom OpenAI-compatible embedding provider", () => {
    render(
      <EmbeddingModelsSection
        providers={[provider]}
        activeModels={{
          active_embedding: {
            provider_id: provider.id,
            model: "embedding-model",
          },
        }}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("Custom Embedding")).toBeInTheDocument();
    expect(
      screen.getByText("Embedding Model (embedding-model)"),
    ).toBeInTheDocument();
  });
});
