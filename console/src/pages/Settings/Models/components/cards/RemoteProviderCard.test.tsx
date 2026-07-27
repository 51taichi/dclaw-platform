import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RemoteProviderCard } from "./RemoteProviderCard";
import type { ProviderInfo } from "../../../../../api/types";

const { mockConfigureProvider, mockMessage, mockConfirm } = vi.hoisted(() => ({
  mockConfigureProvider: vi.fn(),
  mockMessage: {
    error: vi.fn(),
    success: vi.fn(),
  },
  mockConfirm: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

vi.mock("../../../../../api", () => ({
  default: {
    configureProvider: mockConfigureProvider,
    deleteCustomProvider: vi.fn(),
  },
}));

vi.mock("../ProviderIconComponent", () => ({
  ProviderIcon: () => <span data-testid="provider-icon" />,
}));

vi.mock("../modals/ProviderConfigModal", () => ({
  ProviderConfigModal: () => null,
}));

vi.mock("../modals/ModelManageModal", () => ({
  ModelManageModal: () => null,
}));

vi.mock("@agentscope-ai/design", () => {
  const Button = ({
    children,
    onClick,
    ...props
  }: React.PropsWithChildren<{
    onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void;
  }>) => (
    <button onClick={onClick} {...props}>
      {children}
    </button>
  );

  const Modal = {
    confirm: mockConfirm,
  };

  return {
    Button,
    Card: ({ children }: React.PropsWithChildren) => (
      <article>{children}</article>
    ),
    Modal,
  };
});

const provider: ProviderInfo = {
  id: "volcengine-cn",
  name: "Volcano Engine",
  api_key_prefix: "",
  chat_model: "OpenAIChatModel",
  models: [
    {
      id: "doubao",
      name: "Doubao",
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
  base_url: "https://ark.cn-beijing.volces.com/api/v3",
  generate_kwargs: {},
};

describe("RemoteProviderCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfigureProvider.mockResolvedValue(provider);
    mockConfirm.mockImplementation(({ onOk }) => onOk?.());
  });

  it("disables a configured provider without deleting its configuration", async () => {
    const onSaved = vi.fn();

    render(
      <RemoteProviderCard
        provider={provider}
        activeModels={null}
        onSaved={onSaved}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "models.disableProvider" }),
    );

    await waitFor(() => {
      expect(mockConfigureProvider).toHaveBeenCalledWith("volcengine-cn", {
        disabled: true,
      });
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("warns when disabling the active embedding provider", () => {
    render(
      <RemoteProviderCard
        provider={provider}
        activeModels={{
          active_embedding: {
            provider_id: provider.id,
            model: "text-embedding-v4",
          },
        }}
        onSaved={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "models.disableProvider" }),
    );

    expect(mockConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        content: "models.disableProviderConfirmActive",
      }),
    );
  });
});
